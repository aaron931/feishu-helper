FeishuHelper 飞书机器人工具库 — README
FeishuHelper 飞书机器人工具封装
一套轻量化、高可用、可直接接入项目的飞书（Lark）机器人通用工具类，封装飞书常用全部接口，开箱即用，无需额外复杂封装，适合自动化运维、业务推送、内部办公系统对接。

---
✅ 功能亮点
- ✅ 一键发送飞书私聊、群聊消息，支持多人@提醒
- ✅ 群内话题回复、话题转发、跨群转发话题
- ✅ 批量获取部门架构、部门人员列表
- ✅ 飞书任务清单查询、任务详情获取对接
- ✅ 图片/文件上传、文件下载、消息图片资源拉取
- ✅ 自动重试 HTTP 请求、自带网络异常容错机制
- ✅ 支持消息编辑、消息更新
- ✅ 一键创建飞书在线电子表格
- ✅ 自带文件锁，多线程并发安全调用

---
📦 环境依赖
所有第三方依赖已整理，直接安装即可。
安装依赖命令：
pip install -r requirements.txt
依赖包含：requests、urllib3、filelock
其余全部为 Python 内置库，无需额外安装。

---
🚀 快速开始使用
1. 初始化机器人
from Feishu_helper import FeishuBot

bot = FeishuBot(
    app_id="你的飞书APP_ID",
    app_secret="你的飞书APP_SECRET"
)
2. 常用极简调用示例
发送群消息、发私聊、@多人、查部门全部一键调用。

---
📋 全部已封装接口清单
- 发送消息到指定群聊
- 发送私聊消息给个人
- 话题模式回复消息
- 转发话题到群聊
- 转发话题到个人
- 获取部门基础信息
- 获取全部子部门列表
- 获取部门下所有成员 OpenID
- 读取飞书任务清单数据
- 查询单条任务完整详情
- 下载聊天内图片资源
- 本地图片上传飞书接口
- 通用文件上传接口
- 下载飞书云端文件到本地
- 群聊批量@多人发送消息
- 自动创建空白飞书在线表格
- 编辑、更新已发送消息内容

---
⚙️ 适配场景
- 企业内部自动化告警推送
- 运维监控系统消息推送
- 业务流程自动通知员工
- 内部办公系统对接飞书
- 定时任务、日报、周报自动推送

---
💡 使用注意事项
1. 机器人必须提前加入目标群聊，否则无法发消息
2. 调用任务接口，需要把机器人加入对应任务清单
3. APP_ID、APP_SECRET 请勿硬编码上传公开仓库
4. 多线程调用自动加锁，不用担心并发冲突

---
📄 配套文件
本项目配套完整：
- Feishu_helper.py 主工具类
- requirements.txt 依赖清单
- README.md 使用说明文档
from Feishu_helper import FeishuBot

# 初始化飞书机器人
bot = FeishuBot(
    app_id="你的APP_ID",
    app_secret="你的APP_SECRET"
)

# 1. 发送消息到指定群聊
bot.send_message_to_chat('chat_id', '你好', at_open_id)

# 2. 发送消息给个人
bot.send_message_to_person('你好', open_id)

# 3. 以话题形式回复消息
bot.reply_to_message(message_id, message_content, at_user_open_id)

# 4. 转发话题到群聊
bot.reply_to_chat('话题的thread_id', '需要转发的群id')

# 5. 转发话题到个人
bot.reply_to_person('话题的thread_id', '需要转发的open_id')

# 6. 获取部门信息
bot.get_department_info('department_id')

# 7. 获取子部门列表
bot.get_department_list('department_id')

# 8. 获取部门成员列表
bot.get_users_by_department('department_id')

# 9. 获取飞书任务清单（需先将机器人App加入任务清单）
bot.search_feishu_task('task_list_id')

# 10. 获取任务详情
bot.get_task_detail('task_guid')

# 11. 下载图片
bot.get_image('event')

# 12. 上传图片
bot.upload_image('image_path')

# 13. 上传文件
bot.upload_file_with_curl_style(file_path, file_type, file_name)

# 14. 下载飞书文件
bot.download_lark_file('message_id', 'file_token', 'save_path')

# 15. 发送消息到群组（支持@多人）
bot.send_message_to_chat_at_users(
    'chat_id',
    'message_content',
    at_open_ids
)

# 16. 创建空白飞书电子表格
bot.create_feishu_sheet("title", 'creator_open_id')

# 17. 编辑已发送的飞书消息
bot.update_feishu_message('message_id', 'content_text', 'at_open_id')
