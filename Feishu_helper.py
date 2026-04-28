import os
import time
import json
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry  
from pathlib import Path
from filelock import FileLock  # 跨平台文件锁，需安装：pip install filelock
import re
import requests
from datetime import datetime
from typing import Union, List, Dict, Tuple, Any
class FeishuChatBot:
    def __init__(self, app_id, app_secret, token_file_path="tenant_token.json"):
        # 初始化带重试的Session
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

        self.app_id = app_id
        self.app_secret = app_secret
        self.headers = {'Content-Type': 'application/json'}

        # 跨平台文件存储和锁
        self.token_file = Path(token_file_path)
        self.lock_file = Path(f"{token_file_path}.lock")  # 锁文件单独管理
        self.file_lock = FileLock(self.lock_file)  # 使用filelock实现跨平台锁

        # 线程安全控制
        self.thread_lock = threading.Lock()
        self._stop_refresh = False

        # 初始化token
        self.tenant_access_token = None
        self.token_expire_time = 0.0
        self._load_token_from_file()

        # 确保有可用token
        if not self.tenant_access_token or self._is_token_expired():
            self.refresh_tenant_access_token()

        # 启动后台刷新线程
        self.refresh_thread = threading.Thread(target=self._background_refresh, daemon=True)
        self.refresh_thread.start()

        # 新增：超时和重试配置（可根据需要调整）
        self.speech_timeout = 60  # 接口超时时间（秒）
        self.max_retries = 3  # 最大重试次数
        self.retry_base_delay = 2  # 重试基础延迟（秒）

    def _load_token_from_file(self):
        """从文件加载token（多进程共享）"""
        if not self.token_file.exists():
            return False

        try:
            # 使用filelock获取锁，超时10秒
            with self.file_lock.acquire(timeout=10):
                with open(self.token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.tenant_access_token = data.get("tenant_access_token")
                    self.token_expire_time = float(data.get("token_expire_time", 0))
            return True
        except Exception as e:
            print(f"加载token文件失败: {str(e)}")
            return False

    def _save_token_to_file(self):
        """保存token到文件（多进程共享）"""
        try:
            # 使用filelock确保写入安全
            with self.file_lock.acquire(timeout=10):
                with open(self.token_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "tenant_access_token": self.tenant_access_token,
                        "token_expire_time": self.token_expire_time,
                        "updated_at": time.time()
                    }, f, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存token文件失败: {str(e)}")
            return False

    def _is_token_expired(self, ahead_seconds=600):
        """检查token是否已过期或即将过期"""
        return time.time() >= (self.token_expire_time - ahead_seconds)

    def _background_refresh(self):
        """后台刷新线程，动态调整刷新时间"""
        while not self._stop_refresh:
            try:
                # 计算下次刷新时间（提前300秒刷新，最少等待60秒）
                current_time = time.time()
                sleep_seconds = max(60, self.token_expire_time - current_time - 300)

                # 等待到接近过期
                time.sleep(sleep_seconds)

                # 双重检查是否需要刷新
                if self._is_token_expired(300):
                    with self.thread_lock:
                        if self._is_token_expired(300):
                            self.refresh_tenant_access_token()
                            print("后台刷新token成功")
            except Exception as e:
                print(f"后台刷新失败: {str(e)}")
                time.sleep(60)  # 失败后快速重试

    def stop(self):
        """停止后台线程"""
        self._stop_refresh = True
        if self.refresh_thread.is_alive():
            self.refresh_thread.join(timeout=5)
        # 清理锁文件
        if self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except Exception:
                pass

    def get_cached_tenant_access_token(self):
        """获取有效的token，必要时刷新"""
        # 先加载最新的token状态
        self._load_token_from_file()

        # 如果token有效直接返回
        if self.tenant_access_token and not self._is_token_expired():
            return self.tenant_access_token

        # 加锁确保线程安全
        with self.thread_lock:
            # 再次检查，避免重复刷新
            self._load_token_from_file()
            if self.tenant_access_token and not self._is_token_expired():
                return self.tenant_access_token

            # 强制刷新
            self.refresh_tenant_access_token()
            return self.tenant_access_token

    def refresh_tenant_access_token(self):
        """刷新token并更新存储"""
        try:
            url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
            payload = json.dumps({
                "app_id": self.app_id,
                "app_secret": self.app_secret
            })

            response = self.session.post(url, headers=self.headers, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            # 验证返回数据有效性
            if not data or "tenant_access_token" not in data:
                raise ValueError(f"token接口返回无效数据: {data}")

            # 更新token信息
            self.tenant_access_token = data["tenant_access_token"]
            expire_seconds = data.get("expire", 7200)
            self.token_expire_time = time.time() + expire_seconds - 600  # 提前10分钟过期

            # 保存到共享文件
            self._save_token_to_file()

            print(f"已刷新token: {self.tenant_access_token[:8]}...")
            print(f"token剩余有效时间: {int(self.token_expire_time - time.time())}秒")

        except Exception as e:
            print(f"刷新token失败: {str(e)}")
            # 失败后设置短时间过期，允许快速重试
            self.token_expire_time = time.time() + 60
            raise

    # 发送消息到指定群聊
    def send_message_to_chat(self, chat_id, message_content, at_user_id):
        url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "receive_id": chat_id,
            "content": json.dumps({
                "text": f"<at user_id=\"{at_user_id}\"></at> {message_content}" if at_user_id else message_content
            }),
            "msg_type": "text"
        }
        response = requests.post(url, headers=headers, data=json.dumps(data))
        print(f"发送消息结果: {response.json()}")
        # Extract message_id and create_time in milliseconds
        message_id = response.json()['data']['message_id']
        create_time_ms = int(response.json()['data']['create_time'])

        # Convert create_time to human-readable format
        create_time_sec = create_time_ms / 1000
        created_time = datetime.fromtimestamp(create_time_sec).strftime('%Y-%m-%d %H:%M:%S')
        print(message_id, created_time)
        return response.json(), message_id, created_time
    #发送消息给个人
    def send_message_to_person(self, message_content, at_user_id):
        url = "https://open.larksuite.com/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "open_id"}
        msgContent = {
            "text": message_content,
        }
        req = {
            "receive_id": at_user_id,
            "msg_type": "text",
            "content":  json.dumps(msgContent)
        }
        payload = json.dumps(req)
        try:
            response = requests.request("POST", url, params=params, headers=headers, data=payload)
            response.raise_for_status()
            print("Message sent successfully:", response.json())
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error occurred while sending message: {e}")
            return False
    #以话题形式回复
    def reply_to_message(self, message_id, message_content, at_user_ids=None):
        """
        回复指定消息并@指定用户
        :param message_id: 要回复的消息ID
        :param message_content: 回复的内容
        :param at_user_ids: 要@的用户列表（open_id）
        """
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }

        # 构建@用户的内容
        at_content = ""
        if at_user_ids:
            at_tags = [{"tag": "at", "user_id": user_id} for user_id in at_user_ids]
            at_content = " ".join([f"<at user_id=\"{user_id}\">@用户</at>" for user_id in at_user_ids])
        else:
            at_tags = []

        # 完整的消息内容
        msg_content = {
            "text": f"{at_content} {message_content}",
            "mentions": at_tags
        }

        req = {
            "msg_type": "text",
            "reply_in_thread": True,  # 以话题形式回复消息
            "content": json.dumps(msg_content)
        }
        payload = json.dumps(req)

        try:
            response = requests.request("POST", url, headers=headers, data=payload)
            response.raise_for_status()
            print("Reply sent successfully:", response.json())
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error occurred while replying to the message: {e}")
    #转发话题
    def reply_to_chat(self,thread_id,chat_id):
        # 定义 URL 和 Headers
        url = f"https://open.larksuite.com/open-apis/im/v1/threads/{thread_id}/forward"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        # 定义请求参数
        params = {
            "receive_id_type": "chat_id",
        }
        # 定义请求数据
        data = {
            "receive_id": chat_id
        }
        # 发送 POST 请求
        response = requests.post(url, headers=headers, params=params, json=data)
        return response.status_code
    def reply_to_person(self,thread_id,open_id):
        # 定义 URL 和 Headers
        url = f"https://open.larksuite.com/open-apis/im/v1/threads/{thread_id}/forward"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        # 定义请求参数
        params = {
            "receive_id_type": "open_id",
        }
        # 定义请求数据
        data = {
            "receive_id": open_id
        }
        # 发送 POST 请求
        response = requests.post(url, headers=headers, params=params, json=data)
        return response.status_code
    #获取部门信息
    def get_department_info(self,department_id):
        # 请求 URL
        url = (
            "https://open.larksuite.com/open-apis/contact/v3/departments/"
            f"{department_id}"
        )

        # 请求参数
        params = {
            "department_id_type": "open_department_id",
            "user_id_type": "open_id"
        }

        # 请求头
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
        }

        # 发送 GET 请求
        response = requests.get(url, headers=headers, params=params)

        # 输出响应状态码和内容
        return response.json()
    #获取子部门列表
    def get_department_list(self,department_id):
        # 请求 URL
        url = (
            f"https://open.larksuite.com/open-apis/contact/v3/departments/"
            f"{department_id}/children"
        )

        # 请求参数
        params = {
            "department_id_type": "open_department_id",
            "page_size": 50,
            "user_id_type": "open_id"
        }

        # 请求头
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
        }

        # 发送 GET 请求
        response = requests.get(url, headers=headers, params=params)

        # 输出响应状态码和内容
        return response.json()
    # 获取部门成员
    def get_users_by_department(self, department_id):
        url = 'https://open.larksuite.com/open-apis/contact/v3/users/find_by_department'
        params = {
            'department_id': department_id,
            'department_id_type': 'open_department_id',
            'user_id_type': 'open_id',
            'page_size': 50  # 每页返回50个用户
        }
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
        }

        all_users = []  # 用于存储所有用户的数据
        page_token = None  # 用于处理分页

        while True:
            if page_token:
                params['page_token'] = page_token  # 如果有分页标识，加入 page_token

            response = requests.get(url, params=params, headers=headers)

            if response.status_code == 200:
                data = response.json()

                # 获取当前页面的用户数据并加入到all_users中
                all_users.extend(data.get('data', {}).get('items', []))  # 添加当前页的用户

                # 检查是否还有下一页
                page_token = data.get('data', {}).get('page_token', None)
                if not page_token:
                    break  # 如果没有下一页，跳出循环
            else:
                response.raise_for_status()  # 请求失败时抛出异常

        return {'data': all_users}  # 返回所有用户的完整数据（JSON格式）
    #获取飞书任务清单,需要先把机器人app，加入到任务清单
    def search_feishu_task(self, task_list_id):
        url = f"https://open.larksuite.com/open-apis/task/v2/tasklists/{task_list_id}/tasks"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        params = {
            "page_size": 50,  # 每页任务数
            "user_id_type": "open_id"  # 用户 ID 类型
        }

        all_tasks = []
        while True:
            # 发送 GET 请求
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                all_tasks.extend(data.get("data", {}).get("items", []))

                # 检查是否有下一页
                if data.get("data", {}).get("has_more", False):
                    params["page_token"] = data["data"]["page_token"]  # 获取下一页 token
                else:
                    break
            else:
                print("获取任务失败：", response.status_code, response.text)
                return None  # 或者抛出异常
        return all_tasks
    #获取任务详情
    def get_task_detail(self,task_guid):
        url = f'https://open.larksuite.com/open-apis/task/v2/tasks/{task_guid}'
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}"
        }
        params = {
            'user_id_type': 'open_id'
        }

        # 发起 GET 请求
        response = requests.get(url, headers=headers, params=params)

        # 检查响应是否成功
        if response.status_code == 200:
            return response.json()  # 返回任务详情的 JSON 数据
        # else:
        #     return f"Error: {response.status_code}, {response.text}"
    #下载图片
    def get_image(self, event):
        #image_save_path = "/static/feishuimage"
        # 获取当前.py文件所在的目录（core文件夹）
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 向上退一级 → 项目根目录（关键！）
        base_dir = os.path.dirname(current_dir)
        image_save_path = os.path.join(base_dir, "static", "feishuimage")
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}"
        }
        # 确保保存图片的目录存在
        if not os.path.exists(image_save_path):
            os.makedirs(image_save_path)
        try:
            # 解析 `content` 字符串为字典
            content_dict = json.loads(event["content"])
            print(content_dict)
            if isinstance(content_dict, dict):
                if "image_key" in content_dict:
                    # 简单场景 {"image_key": "xxx"}
                    image_keys = [content_dict["image_key"]]
                elif "content" in content_dict:
                    # 复杂嵌套场景
                    image_keys = []
                    for outer_list in content_dict["content"]:
                        for inner_list in outer_list:
                            if inner_list.get("tag") == "img":
                                image_key = inner_list.get("image_key")
                                if image_key:
                                    image_keys.append(image_key)
                else:
                    print("未找到有效的图片键。")
                    return
            else:
                print("解析后的内容不是有效的字典格式。")
                return

            for image_key in image_keys:
                # 构建获取图片的 API URL
                image_url = f"https://open.larksuite.com/open-apis/im/v1/messages/{event.get('message_id')}/resources/{image_key}?type=image"
                try:
                    image_response = requests.get(image_url, headers=headers)
                    if image_response.status_code == 200:
                        # 保存图片到本地
                        image_file_name = f"{event.get('message_id')}_{image_key}.png"
                        image_file_path = os.path.join(image_save_path, image_file_name)
                        with open(image_file_path, 'wb') as f:
                            f.write(image_response.content)
                        print(f"图片 {image_file_name} 下载成功")
                        return image_file_name
                    else:
                        print(f"请求图片 {image_key} 失败，状态码: {image_response.status_code}")
                except requests.RequestException as e:
                    print(f"请求图片 {image_key} 时发生网络错误: {e}")
        except json.JSONDecodeError:
            print("无法解析 content 为有效的 JSON 数据。")

    #图片上传
    def upload_image(self, image_path):
        """上传图片
        Args:
            image_path: 文件上传路径
            image_type: 图片类型
        Return
            {
                "ok": true,
                "image_key": "xxx",
                "url": "https://xxx"
            }
        Raise:
            Exception
                * file not found
                * request error
        """
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}"
            # 注意：不要在这里手动设置 Content-Type: multipart/form-data
            # requests 库会在使用 files 参数时自动处理，并生成正确的 boundary
        }
        with open(image_path, 'rb') as f:
            image = f.read()
        resp = requests.post(
            url='https://open.larksuite.com/open-apis/image/v4/put/',
            headers=headers,
            files={
                "image": image
            },
            data={
                "image_type": "message"
            },
            stream=True)
        resp.raise_for_status()
        content = resp.json()
        if content.get("code") == 0:
            return content
        else:
            raise Exception("Call Api Error, errorCode is %s" % content["code"])
    #文件上传
    def upload_file_with_curl_style(self, file_path, file_type, file_name, duration=None):
        """
        按照指定的 curl 命令格式，上传文件到飞书。

        :param token: 你的访问令牌 (tenant_access_token 或 user_access_token)。
        :param file_path: 本地文件的绝对路径。
        :param file_type: 文件类型，如 "mp4", "audio" 等。
        :param file_name: 在飞书上显示的文件名。
        :param duration: 视频时长（毫秒），仅视频上传时需要。
        :return: 上传成功后返回的文件信息 (dict)。
        """
        url = "https://open.larksuite.com/open-apis/im/v1/files"

        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}"
            # 注意：不要在这里手动设置 Content-Type: multipart/form-data
            # requests 库会在使用 files 参数时自动处理，并生成正确的 boundary
        }

        # 构造 files 参数。这是最关键的一步。
        # 对于每个表单字段，我们都用一个元组来表示:
        # ('form_field_name', ('filename', file_object, 'content_type', headers))
        # - 对于普通文本字段，filename 设为 None，file_object 设为要传递的字符串。
        # - 对于文件字段，filename 设为实际的文件名，file_object 设为文件对象。
        files = {
            'file_type': (None, file_type),
            'file_name': (None, file_name),
            'file': (os.path.basename(file_path), open(file_path, 'rb'), 'application/octet-stream'),
            "purpose": (None, "ai")  # 必须为 'ai'
        }

        # 如果提供了 duration，则添加到 files 字典中
        if duration is not None:
            files['duration'] = (None, str(duration))

        print(f"开始上传文件: {file_path}")
        try:
            # 发送请求
            response = requests.post(url, headers=headers, files=files)
            response_data = response.json()

            if response_data.get("code") != 0:
                raise Exception(f"文件上传失败: {response_data}")

            print("文件上传成功!")
            return response_data

        except FileNotFoundError:
            raise Exception(f"文件未找到: {file_path}")
        except Exception as e:
            raise Exception(f"上传过程中发生错误: {e}")
        finally:
            # 确保文件被关闭
            if 'file' in files and files['file'][1] is not None:
                files['file'][1].close()
    #下载飞书文件
    def download_lark_file(self, message_id: str, file_token: str, save_path: str):
        """
        从 Lark Suite (飞书) 下载文件并保存。

        如果下载成功，文件将被保存到指定路径。
        如果发生任何错误（如网络问题、权限错误、文件写入错误），将直接抛出异常。

        Args:
            message_id (str): 包含文件的消息 ID。
            file_token (str): 文件的唯一令牌。
            access_token (str): 你的应用访问令牌。
            save_path (str): 文件保存的路径（如果是目录，则使用响应头中的文件名）。
        """
        # 1. 构造请求 URL
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}/resources/{file_token}?type=file"

        # 2. 构造请求头
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}"
        }

        # 3. 发送 GET 请求
        with requests.get(url, headers=headers, stream=True) as response:
            # 如果请求失败，raise_for_status() 会抛出 HTTPError 异常
            response.raise_for_status()
            # 4. 从响应头获取文件名
            filename = None
            content_disposition = response.headers.get('Content-Disposition')
            if content_disposition:
                match = re.search(r'filename="?([^";]+)"?', content_disposition)
                if match:
                    filename = match.group(1)

            # 5. 确定最终的保存路径
            if filename:
                # 如果 save_path 是一个已存在的目录，则将文件名追加到目录后
                if os.path.isdir(save_path):
                    save_path = os.path.join(save_path, filename)
                # 如果 save_path 指向一个文件，但我们又从响应头拿到了文件名，
                # 这里我们选择信任响应头的文件名，覆盖掉用户提供的文件名部分
                elif os.path.splitext(save_path)[1] == '':  # 如果用户提供的路径没有扩展名
                    save_path = f"{save_path}_{filename}"

            # 6. 写入文件
            with open(save_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

            print(f"文件下载成功！已保存至: {save_path}")

    #发送内容到群组，可以支持多at人情况  
    def send_message_to_chat_at_users(
            self,
            chat_id: str,
            message_content: str,
            at_mapping: Union[Dict[int, Union[str, List[str]]], List[str], str, None] = None,
            at_prefix: str = ". "
    ) -> Tuple[Dict[str, Any], str, str]:
        """
        修复：支持序号对应多个@用户ID（列表）的场景
        """
        # 校验必填参数
        if not chat_id or not message_content:
            return {"code": -4, "msg": "chat_id/消息内容不能为空"}, "", ""

        url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        final_content = message_content

        # ========== 核心修复：支持单个/多个用户ID ==========
        if isinstance(at_mapping, dict):
            sorted_indices = sorted(at_mapping.keys(), reverse=True)
            for idx in sorted_indices:
                if not isinstance(idx, int) or idx < 1:
                    continue
                at_user_ids = at_mapping[idx]
                if not at_user_ids:
                    continue

                # 统一转为列表处理（兼容单个字符串/列表）
                if isinstance(at_user_ids, str):
                    at_user_list = [at_user_ids.strip()]
                elif isinstance(at_user_ids, list):
                    at_user_list = [uid.strip() for uid in at_user_ids if isinstance(uid, str) and uid.strip()]
                else:
                    continue

                # 生成多个@标签
                at_tags = [f"<at user_id=\"{uid}\"></at>" for uid in at_user_list]
                at_tags_str = " ".join(at_tags)

                # 替换对应序号位置
                target_str = f"{idx}{at_prefix}"
                replace_str = f"{idx}{at_prefix}{at_tags_str} "
                final_content = final_content.replace(target_str, replace_str, 1)

        # 兼容原有批量@逻辑
        elif at_mapping:
            at_users = []
            if isinstance(at_mapping, str):
                at_users = [uid.strip() for uid in at_mapping.split(",") if uid.strip()]
            elif isinstance(at_mapping, list):
                at_users = [uid.strip() for uid in at_mapping if isinstance(uid, str) and uid.strip()]

            if at_users:
                at_tags = [f"<at user_id=\"{uid}\"></at>" for uid in at_users]
                final_content = " ".join(at_tags) + " " + final_content

        # 构造请求数据
        data = {
            "receive_id": chat_id,
            "content": json.dumps({"text": final_content}, ensure_ascii=False),
            "msg_type": "text"
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=10
            )
            response.raise_for_status()
            response_json = response.json()

            if response_json.get("code") == 0 and "data" in response_json:
                message_id = response_json['data'].get('message_id', '')
                create_time_ms = response_json['data'].get('create_time', 0)
                created_time = ""
                if create_time_ms:
                    try:
                        create_time_sec = int(create_time_ms) / 1000
                        created_time = datetime.fromtimestamp(create_time_sec).strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        created_time = ""
                return response_json, message_id, created_time
            else:
                print(f"发送失败: {response_json}")
                return response_json, "", ""

        except requests.exceptions.RequestException as e:
            err_msg = f"请求异常: {str(e)}"
            print(err_msg)
            return {"code": -1, "msg": err_msg}, "", ""
        except Exception as e:
            err_msg = f"未知错误: {str(e)}"
            print(err_msg)
            return {"code": -3, "msg": err_msg}, "", ""


    # ===================== 1. 创建空白飞书电子表格 =====================
    def create_feishu_sheet(self, title="客户数据统计表", creator_open_id=''):
        """
        创建飞书在线电子表格(Sheet) - 带完整排查日志
        :param title: 表格名称
        :return: sheet_token(表格唯一标识), sheet_url(表格原始链接)
        """
        url = "https://open.larksuite.com/open-apis/sheets/v3/spreadsheets"
        data = {
            "title": title,
            "folder_token": "",  # 为空则创建在「我的空间」根目录
            "creator_id": creator_open_id
        }
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        res = requests.post(url, headers=headers, data=json.dumps(data))
        res_json = res.json()
        # ============ 新增：紧急排查 - 打印完整返回值 ============
        print("⚠️ 飞书创建表格接口完整返回内容：", res_json)
        print("⚠️ 接口响应状态码：", res.status_code)
        # ========================================================
        if res_json.get("code") == 0:
            sheet_token = res_json["data"]["spreadsheet"]["spreadsheet_token"]
            sheet_url = res_json["data"]["spreadsheet"]["url"]
            print(f"✅ 表格创建成功 → token: {sheet_token}, 链接: {sheet_url}")
            return sheet_token, sheet_url
        else:
            print(f"❌ 创建表格失败: {res_json}")
            return None, None

    #===================================================================飞书消息编辑======================================
    def update_feishu_message(self, message_id: str, content_text: str, at_id: str = None) -> dict:
        """
        编辑飞书消息（支持可选原生@人，触发系统提醒，兼容原有纯文本调用）
        :param message_id: 飞书消息ID
        :param content_text: 消息正文内容
        :param at_id: 可选，要@人的飞书ID（ou_/u_开头均可，飞书接口兼容）
        :param at_name: 可选，要@人的姓名（如：解存岗）
        :return: 飞书接口返回的json字典
        :raises: requests.exceptions.RequestException - 请求失败时抛出异常
        """
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.tenant_access_token}"
        }

        # 核心：如果传入了at_id和at_name，自动拼接@人标签到正文头部
        if at_id:
            final_content = f'<at user_id="{at_id}"></at> {content_text}'
        else:
            final_content = content_text  # 未传则使用原正文，兼容原有调用

        data = {
            "msg_type": "text",
            # 关键：ensure_ascii=False 防止@标签/中文被转义成Unicode，飞书接口才能识别
            "content": json.dumps({"text": final_content}, ensure_ascii=False)
        }

        response = requests.put(url=url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()




