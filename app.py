from flask import Flask, Response, jsonify
import json
import re
import requests
import time
import logging
import concurrent.futures

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 核心配置参数
MAX_CHANNELS = 20  # 减少频道数，适应Vercel环境
MAX_RETRIES = 2    # 减少重试次数，避免超时
TIMEOUT = 8        # 减少超时时间，适应Vercel环境
RETRY_DELAY = 0.3  # 减少重试间隔时间

# Flask应用实例初始化
app = Flask(__name__)

# 读取频道配置数据
# 从channels.json文件中加载频道配置信息
def read_channels_json():
    with open('channels.json', 'r', encoding='utf-8') as f:
        return json.load(f)

# URL提取器
# 从HTML内容中智能提取直播源URL，确保t和token参数是实时爬取的
# 严格验证提取的URL，避免任何硬编码或计算生成的参数
def extract_url(html_content):
    # 处理HTML内容中的各种转义情况
    html_content = html_content.replace('\\/', '/')
    html_content = html_content.replace('\\"', '"')
    
    # 模式1: 优先匹配包含t和token参数的完整URL格式
    # 使用更精确的正则表达式确保捕获完整的带参数URL
    token_pattern = r'(https://cdn\.inteltelevision\.com[^\s"\']+t=[^"&]+&token=[^"&]+)'
    match = re.search(token_pattern, html_content)
    if match:
        url = match.group(1)
        # 严格验证URL参数格式，确保t和token是从网页中提取的实时参数
        if 't=' in url and 'token=' in url:
            # 提取t和token参数值进行记录验证
            t_match = re.search(r't=([^&]+)', url)
            token_match = re.search(r'token=([^&]+)', url)
            if t_match and token_match:
                t_value = t_match.group(1)
                token_value = token_match.group(1)
                # 记录提取到的实时参数值，便于验证
                logger.info(f"成功提取带实时参数的URL - t={t_value[:8]}..., token={token_value[:8]}...")
                return url
    
    # 模式2: 从JavaScript变量中提取sourceData数据
    source_data_pattern = r'var sourceData\s*=\s*(\[.*?\]);'
    match = re.search(source_data_pattern, html_content, re.DOTALL)
    if match:
        try:
            source_data_str = match.group(1)
            source_data_str = source_data_str.replace('\\"', '"')
            source_data_str = source_data_str.replace('\\/', '/')
            
            data = json.loads(source_data_str)
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if isinstance(item, dict) and 'url' in item:
                        url = item['url']
                        # 严格验证URL必须包含t和token参数
                        if 't=' in url and 'token=' in url:
                            t_match = re.search(r't=([^&]+)', url)
                            token_match = re.search(r'token=([^&]+)', url)
                            if t_match and token_match:
                                t_value = t_match.group(1)
                                token_value = token_match.group(1)
                                logger.info(f"通过sourceData提取到实时参数URL - t={t_value[:8]}..., token={token_value[:8]}...")
                                return url
        except Exception as e:
            logger.error(f"JSON解析失败: {str(e)}")
    
    # 模式3: 查找所有可能的IntelTV M3U8链接，但仍然必须包含完整参数
    intel_pattern = r'(https://cdn\.inteltelevision\.com[^\s"\']+\.m3u8[^"\']*)'
    match = re.search(intel_pattern, html_content)
    if match:
        url = match.group(1)
        if 't=' in url and 'token=' in url:
            t_match = re.search(r't=([^&]+)', url)
            token_match = re.search(r'token=([^&]+)', url)
            if t_match and token_match:
                t_value = t_match.group(1)
                token_value = token_match.group(1)
                logger.info(f"找到带实时参数的M3U8 URL - t={t_value[:8]}..., token={token_value[:8]}...")
                return url
    
    logger.warning("未找到有效的带t和token参数的实时URL")
    return None

# 增强型HTTP请求函数
# 封装带会话管理和自动重试功能的网络请求，提高爬取成功率
def request_with_retry(url, headers, timeout):
    with requests.Session() as session:
        session.headers.update(headers)
        session.keep_alive = True
        
        for retry in range(MAX_RETRIES + 1):
            try:
                # 不使用stream=True，确保读取完整内容以捕获所有URL参数
                response = session.get(url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
                
                # 读取完整HTML内容
                html_content = response.text
                return html_content
                
            except Exception as e:
                if retry < MAX_RETRIES:
                    wait_time = RETRY_DELAY * (retry + 1)
                    logger.warning(f"请求失败，{retry + 1}/{MAX_RETRIES + 1} 重试... 等待 {wait_time}秒 - {str(e)}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"请求失败，已达最大重试次数: {str(e)}")
                    raise e

# 频道处理函数
# 处理单个频道的爬取逻辑，包括URL构建、请求发送和URL提取
def process_channel(channel):
    try:
        name = channel['name']
        page = channel['page']
        
        # 构建完整URL
        base_url = "https://www.kds.tw/tv/china-tv-channels-online/"
        if page.startswith('http'):
            full_url = page
        else:
            full_url = base_url + page
        
        logger.info(f"正在爬取: {name}")
        
        # 设置真实的请求头，模拟浏览器行为
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.kds.tw/',
        }
        
        # 使用带重试机制的请求获取完整HTML内容
        html_content = request_with_retry(full_url, headers, TIMEOUT)
        
        # 使用优化的URL提取函数
        url = extract_url(html_content)
        if url:
            # 再次验证URL确实是从页面提取的，而不是拼接的
            if 'cdn.inteltelevision.com' in url and 't=' in url and 'token=' in url:
                logger.info(f"成功提取真实URL: {name}")
                return (name, url)
        
        logger.warning(f"未找到有效URL: {name}")
        return (name, None)
        
    except Exception as e:
        logger.error(f"爬取失败: {channel.get('name', 'Unknown')} - {str(e)}")
        return (channel.get('name', 'Unknown'), None)

# 爬虫主控制器
# 协调整个爬取流程，使用多线程处理，包括数据读取、并发控制和结果整合
def run_spider():
    logger.info("开始运行爬虫")
    start_time = time.time()
    
    # 读取频道数据
    data = read_channels_json()
    
    # 收集所有需要处理的频道
    channels_to_process = []
    for group in data[:1]:  # 只处理第一个分组
        channels_to_process.extend(group['channels'][:MAX_CHANNELS])
    
    # 存储频道URL映射的字典
    channel_urls = {}
    
    # 在Vercel环境中减少并发数，避免资源限制
    max_workers = min(5, len(channels_to_process))  # 减少线程数，适应Vercel无服务器环境
    logger.info(f"使用多线程并发处理，线程数: {max_workers}")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_channel = {executor.submit(process_channel, channel): channel for channel in channels_to_process}
        
        # 获取结果
        for future in concurrent.futures.as_completed(future_to_channel):
            name, url = future.result()
            if url:
                channel_urls[name] = url
    
    # 构建结果
    # 从channels.json的group-title中动态获取频道组名
    group_title = data[0].get('group-title')
    results = [f"{group_title},#genre#"]  # 添加分类行
    
    # 遍历原始数据结构，保持原始顺序
    for group in data[:1]:
        for channel in group['channels'][:MAX_CHANNELS]:
            name = channel['name']
            if name in channel_urls:
                results.append(f"{name},{channel_urls[name]}")
            else:
                # 标记无法获取的频道
                results.append(f"{name},#ERROR#")
    
    # 将结果转换为文本
    live_content = '\n'.join(results)
    
    end_time = time.time()
    logger.info(f"爬取完成！耗时: {end_time - start_time:.2f}秒，共获取{len(channel_urls)}个频道的URL")
    
    return live_content

# 直播源文件接口
# 返回直播源文件内容，直接在浏览器中显示而不是下载
@app.route('/live.txt')
def get_live_file():
    try:
        # 运行爬虫获取最新内容
        live_content = run_spider()
        
        # 返回文本内容，直接在浏览器中显示
        return Response(
            live_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': 'inline',
                'Content-Length': str(len(live_content)),
                'Cache-Control': 'no-cache'
            }
        )
    except Exception as e:
        logger.error(f"处理/live.txt请求时出错: {str(e)}")
        # 返回简单的错误信息
        error_content = f"Error: {str(e)}"
        return Response(
            error_content,
            mimetype='text/plain',
            status=500
        )

# 根路径接口
# 访问根路径时直接返回直播源文件内容
@app.route('/')
def root():
    return get_live_file()

# 健康检查接口
# 用于监控系统状态和服务可用性
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time()
    })

# 应用入口
if __name__ == '__main__':
    # 本地开发环境配置
    app.run(host='0.0.0.0', port=8000, debug=False)

# Vercel平台部署入口
# 这是Vercel Python支持的正确导出方式
# 确保app对象可以被Vercel导入
__name__ = "app"
# 创建ASGI兼容的入口点
from werkzeug.wrappers import Request, Response

def application(environ, start_response):
    """ASGI兼容的应用入口"""
    return app(environ, start_response)
