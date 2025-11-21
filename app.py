from flask import Flask, Response, jsonify, stream_with_context
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
MAX_RETRIES = 1    # 减少重试次数，提高速度
TIMEOUT = 5        # 减少超时时间，提高速度
RETRY_DELAY = 0.2  # 减少重试间隔时间

# Flask应用实例初始化
app = Flask(__name__)

# 读取频道配置数据
# 从channels.json文件中加载频道配置信息
def read_channels_json():
    with open('channels.json', 'r', encoding='utf-8') as f:
        return json.load(f)

# URL提取器
# 简化版，专注于从var sourceData变量中提取直播源URL
def extract_url(html_content):
    try:
        # 处理HTML内容中的转义字符
        html_content = html_content.replace('\\/', '/')
        html_content = html_content.replace('\\"', '"')
        
        # 只查找var sourceData变量中的URL
        source_data_pattern = r'var sourceData\s*=\s*(\[.*?\]);'
        match = re.search(source_data_pattern, html_content, re.DOTALL)
        if match:
            source_data_str = match.group(1)
            # 进一步处理转义字符
            source_data_str = source_data_str.replace('\\"', '"')
            source_data_str = source_data_str.replace('\\/', '/')
            
            # 解析JSON
            data = json.loads(source_data_str)
            if isinstance(data, list) and len(data) > 0:
                # 获取第一个有效URL
                for item in data:
                    if isinstance(item, dict) and 'url' in item:
                        url = item['url']
                        # 验证URL格式
                        if 'cdn.inteltelevision.com' in url and '.m3u8' in url:
                            logger.info(f"成功从sourceData提取URL")
                            return url
    except Exception as e:
        logger.error(f"提取URL失败: {str(e)}")
    
    logger.warning("未找到有效的URL")
    return None

# 优化的HTTP请求函数
# 使用会话复用和连接池提高请求效率
def request_with_retry(url, headers, timeout):
    # 复用会话对象以提高性能
    with requests.Session() as session:
        session.headers.update(headers)
        session.keep_alive = True
        # 设置连接池参数
        session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=100))
        
        for retry in range(MAX_RETRIES + 1):
            try:
                response = session.get(url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
                # 只返回需要的文本内容
                return response.text
                
            except Exception as e:
                if retry < MAX_RETRIES:
                    wait_time = RETRY_DELAY * (retry + 1)
                    logger.warning(f"请求失败，{retry + 1}/{MAX_RETRIES + 1} 重试... 等待 {wait_time}秒")
                    time.sleep(wait_time)
                else:
                    logger.error(f"请求失败，已达最大重试次数")
                    raise e

# 频道处理函数
# 简化版，直接从指定URL构建并提取sourceData中的URL
def process_channel(channel):
    try:
        name = channel['name']
        page = channel['page']
        
        # 直接构建完整URL，严格按照要求拼接
        base_url = "https://www.kds.tw/tv/china-tv-channels-online/"
        full_url = base_url + page
        
        logger.info(f"正在爬取: {name} - {full_url}")
        
        # 优化的请求头，专注于必要信息
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Referer': 'https://www.kds.tw/',
        }
        
        # 获取HTML内容
        html_content = request_with_retry(full_url, headers, TIMEOUT)
        
        # 提取URL
        url = extract_url(html_content)
        if url:
            logger.info(f"成功提取URL: {name}")
            return (name, url)
        
        logger.warning(f"未找到有效URL: {name}")
        return (name, None)
        
    except Exception as e:
        logger.error(f"爬取失败: {channel.get('name', 'Unknown')}")
        return (channel.get('name', 'Unknown'), None)

# 流式爬虫控制器
# 实现边爬取边输出的功能
def stream_spider():
    logger.info("开始运行流式爬虫")
    start_time = time.time()
    
    # 读取频道数据
    data = read_channels_json()
    
    # 存储已处理的频道URL
    processed_channels = {}
    
    # 遍历每个分组
    for i, group in enumerate(data):
        # 在不是第一个分组时，添加两个换行符作为分隔
        if i > 0:
            yield '\n'
            yield '\n'
            
        group_title = group.get('group-title')
        # 输出分类行
        yield f"{group_title},#genre#\n"
        
        # 获取该分组的频道
        channels = group['channels'][:MAX_CHANNELS]
        
        # 判断是否为央视频道分组
        if group_title == "央视频道":
            logger.info("央视频道分组，按顺序处理")
            # 央视频道按顺序处理，逐个执行
            for channel in channels:
                name, url = process_channel(channel)
                if url:
                    processed_channels[name] = url
                    # 立即输出获取到的频道信息
                    yield f"{name},{url}\n"
                else:
                    # 标记无法获取的频道
                    yield f"{name},#ERROR#\n"
        else:
            logger.info(f"{group_title}分组，并行实时处理")
            # 对于其他分组（如卫视频道），使用线程池并行处理并实时返回
            # 增加并发数以提高爬取速度
            max_workers = min(8, len(channels))
            
            # 使用线程池处理该分组的所有频道
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_channel = {executor.submit(process_channel, channel): channel for channel in channels}
                
                # 一旦有结果就立即输出
                for future in concurrent.futures.as_completed(future_to_channel):
                    name, url = future.result()
                    if url:
                        processed_channels[name] = url
                        # 立即输出获取到的频道信息
                        yield f"{name},{url}\n"
                    else:
                        # 标记无法获取的频道
                        yield f"{name},#ERROR#\n"
    
    end_time = time.time()
    logger.info(f"爬取完成！耗时: {end_time - start_time:.2f}秒，共获取{len(processed_channels)}个频道的URL")

# 保留原有的run_spider函数供其他地方调用
def run_spider():
    # 收集所有输出
    output_lines = []
    for line in stream_spider():
        output_lines.append(line.rstrip('\n'))
    return '\n'.join(output_lines)

# 直播源文件接口
# 返回直播源文件内容，使用流式响应实现边爬取边显示
@app.route('/live.txt')
def get_live_file():
    try:
        # 使用流式响应，设置stream_with_context=True支持流式处理
        return Response(
            stream_with_context(stream_spider()),
            mimetype='text/plain',
            headers={
                'Content-Disposition': 'inline',
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
