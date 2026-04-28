import os
import time
import json
import threading
import base64
import io
import re
import random
import string
import secrets
import numpy as np
import soundfile as sf
import librosa
import requests
from datetime import datetime
from typing import Union
from functools import wraps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
from filelock import FileLock
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("FeishuHelper")


# ===================== 限流装饰器 =====================
def rate_limiter(max_qps: int = 20):
    interval = 1.0 / max_qps
    last_called = 0.0

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal last_called
            current = time.time()
            elapsed = current - last_called
            if elapsed < interval:
                time.sleep(interval - elapsed)
            last_called = time.time()
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ===================== 飞书通用工具类 =====================
class FeishuBot:
    def __init__(self, app_id, app_secret, token_file="tenant_token.json"):
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

        self.app_id = app_id
        self.app_secret = app_secret
        self.headers = {"Content-Type": "application/json"}

        self.token_file = Path(token_file)
        self.lock_file = Path(f"{token_file}.lock")
        self.file_lock = FileLock(self.lock_file)
        self.thread_lock = threading.Lock()
        self._stop_refresh = False

        self.tenant_access_token = None
        self.token_expire_time = 0.0

        self._load_token_from_file()
        if not self.tenant_access_token or self._is_token_expired():
            self.refresh_tenant_access_token()

        self.refresh_thread = threading.Thread(target=self._background_refresh, daemon=True)
        self.refresh_thread.start()

        self.speech_timeout = 60
        self.max_retries = 3
        self.retry_base_delay = 2

    def _load_token_from_file(self):
        if not self.token_file.exists():
            return False
        try:
            with self.file_lock.acquire(timeout=10):
                with open(self.token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.tenant_access_token = data.get("tenant_access_token")
                    self.token_expire_time = float(data.get("token_expire_time", 0))
            return True
        except Exception as e:
            logger.warning(f"加载token失败: {e}")
            return False

    def _save_token_to_file(self):
        try:
            with self.file_lock.acquire(timeout=10):
                with open(self.token_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "tenant_access_token": self.tenant_access_token,
                        "token_expire_time": self.token_expire_time
                    }, f)
            return True
        except Exception as e:
            logger.warning(f"保存token失败: {e}")
            return False

    def _is_token_expired(self, ahead=600):
        return time.time() >= self.token_expire_time - ahead

    def _background_refresh(self):
        while not self._stop_refresh:
            try:
                wait = max(60, self.token_expire_time - time.time() - 300)
                time.sleep(wait)
                if self._is_token_expired(300):
                    with self.thread_lock:
                        if self._is_token_expired(300):
                            self.refresh_tenant_access_token()
            except Exception as e:
                logger.error(f"后台刷新失败: {e}")
                time.sleep(60)

    def stop(self):
        self._stop_refresh = True
        if self.refresh_thread.is_alive():
            self.refresh_thread.join(timeout=5)
        try:
            self.lock_file.unlink()
        except:
            pass

    def get_token(self):
        self._load_token_from_file()
        if self.tenant_access_token and not self._is_token_expired():
            return self.tenant_access_token
        with self.thread_lock:
            self._load_token_from_file()
            if self.tenant_access_token and not self._is_token_expired():
                return self.tenant_access_token
            self.refresh_tenant_access_token()
            return self.tenant_access_token

    def refresh_tenant_access_token(self):
        url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        data = {"app_id": self.app_id, "app_secret": self.app_secret}
        resp = self.session.post(url, json=data, timeout=10)
        resp.raise_for_status()
        r = resp.json()
        self.tenant_access_token = r["tenant_access_token"]
        expire = r.get("expire", 7200)
        self.token_expire_time = time.time() + expire - 600
        self._save_token_to_file()
        logger.info("Token 刷新成功")

    # -------------------------------------------------------------------------
    # 消息发送
    # -------------------------------------------------------------------------
    def send_text(self, receive_id_type, receive_id, text):
        url = "https://open.larksuite.com/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json"
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text})
        }
        params = {"receive_id_type": receive_id_type}
        resp = self.session.post(url, headers=headers, json=payload, params=params)
        return resp.json()

    def send_card(self, receive_id_type, receive_id, card):
        url = "https://open.larksuite.com/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json"
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card)
        }
        params = {"receive_id_type": receive_id_type}
        resp = self.session.post(url, headers=headers, json=payload, params=params)
        return resp.json()

    def reply_text(self, message_id, content, at_users=None):
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}/reply"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        text = content
        if at_users:
            ats = "".join([f'<at user_id="{u}"></at>' for u in at_users])
            text = ats + " " + text
        data = {
            "msg_type": "text",
            "reply_in_thread": True,
            "content": json.dumps({"text": text})
        }
        resp = self.session.post(url, headers=headers, json=data)
        return resp.json()

    def update_message(self, message_id, text):
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        data = {
            "msg_type": "text",
            "content": json.dumps({"text": text})
        }
        resp = self.session.put(url, headers=headers, json=data)
        return resp.json()

    # -------------------------------------------------------------------------
    # 文件 / 图片 / 音频
    # -------------------------------------------------------------------------
    def upload_image(self, path):
        url = "https://open.larksuite.com/open-apis/image/v4/put/"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        with open(path, "rb") as f:
            files = {"image": f}
            data = {"image_type": "message"}
            resp = self.session.post(url, headers=headers, files=files, data=data)
        return resp.json()

    def upload_file(self, file_path, file_name, file_type):
        url = "https://open.larksuite.com/open-apis/im/v1/files"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        files = {
            "file_type": (None, file_type),
            "file_name": (None, file_name),
            "file": (os.path.basename(file_path), open(file_path, "rb"), "application/octet-stream"),
            "purpose": (None, "ai")
        }
        resp = self.session.post(url, headers=headers, files=files)
        return resp.json()

    def download_file(self, msg_id, file_token, save_path):
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{msg_id}/resources/{file_token}?type=file"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        with self.session.get(url, headers=headers, stream=True) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        return save_path

    # -------------------------------------------------------------------------
    # 语音识别
    # -------------------------------------------------------------------------
    def _rand_id(self):
        chars = string.ascii_lowercase + string.digits
        return ''.join(secrets.choice(chars) for _ in range(16))

    def convert_audio_to_pcm(self, stream):
        data, sr = sf.read(stream)
        if data.ndim > 1:
            data = np.mean(data, axis=1)
        if sr != 16000:
            data = librosa.resample(data, orig_sr=sr, target_sr=16000)
        pcm = (data * 32767).astype(np.int16)
        out = io.BytesIO()
        out.write(pcm.tobytes())
        out.seek(0)
        return out

    @rate_limiter(20)
    def speech_to_text(self, base64_pcm):
        url = "https://open.larksuite.com/open-apis/speech_to_text/v1/speech/file_recognize"
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json"
        }
        data = {
            "speech": {"speech": base64_pcm},
            "config": {
                "engine_type": "16k_auto",
                "file_id": self._rand_id(),
                "format": "pcm"
            }
        }
        resp = self.session.post(url, headers=headers, json=data, timeout=60)
        return resp.json()

    # -------------------------------------------------------------------------
    # Wiki / 文档
    # -------------------------------------------------------------------------
    def get_wiki_tree(self, space_id, parent=""):
        items = []
        page = ""
        while True:
            url = f"https://open.larksuite.com/open-apis/wiki/v2/spaces/{space_id}/nodes"
            headers = {"Authorization": f"Bearer {self.get_token()}"}
            params = {"parent_node_token": parent, "page_token": page, "page_size": 50}
            resp = self.session.get(url, headers=headers, params=params).json()
            if resp.get("code") != 0:
                break
            data = resp["data"]
            items += data.get("items", [])
            if not data.get("has_more"):
                break
            page = data["page_token"]
        return items

    def get_doc_markdown(self, doc_id):
        url = "https://open.larksuite.com/open-apis/docs/v1/content"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        params = {"content_type": "markdown", "doc_token": doc_id, "doc_type": "docx"}
        return self.session.get(url, headers=headers, params=params).json()