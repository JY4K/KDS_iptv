<p align="center"><img alt="[https://www.kds.tw/](https://www.kds.tw/)" src="https://raw.githubusercontent.com/JY4K/KDS_iptv/refs/heads/main/KDS.TW.png"></p>
<h1 align="center"> ✯ 一个基于KDS IPTV 直播频道爬虫项目 ✯ </h1>

## 项目简介
KDS IPTV 是一个基于 Flask 开发的轻量级直播频道服务，用于爬取获取KDS.TW网站上的直播源地址。

## 功能特点
- 自动爬取KDS网站图片的直播源地址
- 多线程并发处理，提高爬取效率
- 带重试机制的请求处理，确保稳定性
- 支持导出为 `live.txt` 格式
- 兼容 Vercel 一键部署
- 提供健康检查接口

## 快速开始

### 本地开发

```bash
# 克隆仓库
git clone https://github.com/yourusername/kds-iptv.git
cd kds-iptv

# 安装依赖
pip install -r requirements.txt

# 运行服务
python app.py
```

访问 `http://127.0.0.1:8000/` 获取KDS.TW直播源，或 `http://127.0.0.1:8000/live.txt` 直接下载。

### Vercel 部署

点击下方按钮一键部署到 Vercel：

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/yourusername/kds-iptv)

## API 接口

- `GET /` - 返回直播源文件内容
- `GET /live.txt` - 下载直播源文件
- `GET /health` - 健康检查接口

## 项目结构

```
├── app.py          # 主应用程序
├── channels.json   # 频道配置文件
├── requirements.txt # Python依赖
├── vercel.json     # Vercel部署配置
└── README.md       # 项目说明文档
```

## 注意事项

- 本项目仅供学习和研究使用
- 请尊重KDS网站的内容版权
- 定时更新频道配置以确保可用性
