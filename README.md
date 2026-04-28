# feishu-helper
极简、稳定、开箱即用的飞书 Python SDK

## 功能
- 自动刷新 tenant_access_token（后台线程 + 文件缓存）
- 发送文本消息
- 发送卡片消息
- 回复消息、@用户、编辑消息
- 上传图片/文件
- 下载消息文件
- 语音转文字（ASR）
- 获取 Wiki 知识库目录
- 获取云文档 Markdown 内容

## 安装
pip install requests soundfile librosa filelock urllib3
plaintext

## 快速开始
```python
from feishu import FeishuBot

bot = FeishuBot(
    app_id="你的APP_ID",
    app_secret="你的APP_SECRET"
)

# 发消息
bot.send_text(
    receive_id_type="chat_id",
    receive_id="oc_xxx",
    text="你好，我是 FeishuHelper"
)
