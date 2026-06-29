import os
import requests
from urllib.parse import urlparse
import asyncio
import socket
import ssl
import json
from pathlib import Path
from app.utils.websocket import WebSocketClient
from typing import Callable, List
import warnings
from urllib3.exceptions import InsecureRequestWarning

from app.common import get_logger, DownloadQueue, ChatRequest, GetMessagesRequest, Utils
logger = get_logger()

class Backend:
    user_id = -1
    user_name = ""
    access_token = ""
    on_incoming_message: List[Callable[[dict], None]] = []
    download_queue = DownloadQueue()
    ws_task = None
    websocket_client = None

    @classmethod
    def init(cls, config):
        cls.config = config
        
        cls.url = f"https://{cls.config.host}:{cls.config.port}"
        cls.uri = f"wss://{cls.config.host}:{cls.config.port}/ws"

        paths = [
            Path("/chat/app/rueckgrat-caddy.cert"), 
            Path(os.path.expanduser('~/.ssh/rueckgrat-caddy.cert'))
        ]

        cert = next((p for p in paths if p.exists()), None)
        if not cert:
            cls.server_cert = False
            logger.error(f"failed to get certificate from hub")
        else:
            cls.server_cert = cert

        logger.info(f"using backend at {cls.url}")
        logger.info(f"websocket at {cls.uri}")
        logger.info(f"server_cert {cls.server_cert}")

    @classmethod
    def get_user_name(cls):
        return cls.user_name

    @classmethod
    def shutdown(cls):
        cls.download_queue.stop()

    @classmethod
    def download_file(cls, image_path: str, download_path: str, max_retry: int = 5):
        url = f"{cls.url}/downloads/{image_path}"
        cls.download(url, download_path, max_retry)

    @classmethod
    def download(cls, url: str, download_path: str, asynchronous: bool = True, callback=None, max_retry: int = 5, force_download: bool=False):
        if asynchronous:
            cls.download_queue.add(
                url=url, 
                download_path=download_path, 
                access_token=cls.access_token, 
                server_cert=cls.server_cert, 
                max_retry=max_retry,
                force_download=force_download,
                callback=callback)
        else:
            cls.download_queue.download(
                url=url, 
                download_path=download_path, 
                access_token=cls.access_token, 
                server_cert=cls.server_cert, 
                force_download=force_download
            )

    @classmethod
    async def _on_login_success(cls, token: str):
        cls.ws_task = asyncio.create_task(cls._start_websocket(token))

    @classmethod
    async def stop_websocket(cls):
        if cls.ws_task:
            cls.ws_task.cancel()
            try:
                await cls.ws_task
            except asyncio.CancelledError:
                pass

    @classmethod
    async def _start_websocket(cls, token: str):
        if cls.websocket_client and cls.websocket_client.is_connected():
            return
        cls.websocket_client = WebSocketClient(cls.uri, cls.server_cert)
        cls.websocket_client.set_on_message(cls._on_incomming_websocket)
        await cls.websocket_client.connect(token)

    @classmethod
    def chat(cls, contact_id: int, conversation_id: int, role: str, content: str, temperature: float):
        chat_request = ChatRequest(
            contact_id=contact_id,
            conversation_id=conversation_id,
            role=role,
            name=cls.user_name,
            content=content,
            temperature=temperature
        )
        payload = {"chat": chat_request.model_dump()}
        asyncio.get_event_loop().create_task(cls._send_async_payload(json.dumps(payload)))

    @classmethod
    def generate(cls, prompt: dict):
        payload = {"generate": prompt}
        asyncio.get_event_loop().create_task(cls._send_async_payload(json.dumps(payload)))

    @classmethod
    async def _send_async_payload(cls, payload):
        if cls.websocket_client:
            await cls.websocket_client.send_message(payload)

    @classmethod
    def _on_incomming_websocket(cls, msg: dict):
        try:
            for func in cls.on_incoming_message:
                func(msg)
        except Exception as e:
            logger.error(f"failed to handle incomming message: {repr(e)}")

    @classmethod
    def unregister_incomming_message(cls, callback: Callable[[dict], None]):
        if callback in cls.on_incoming_message:
            cls.on_incoming_message.remove(callback)

    @classmethod
    def register_incomming_message(cls, callback: Callable[[dict], None]):
        cls.on_incoming_message.append(callback)

    @classmethod
    def check_health(cls):
        url = f"{cls.url}/health"
        try:
            response = requests.get(url, timeout=9, verify=cls.server_cert)
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "error")
                if status == "error":
                    logger.error(f"failed to check health: {data.get('message', '')}")
                    return False
                logger.debug("system is healthy")
                return True
            else:
                logger.error(f"lost connection - {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"failed health check: {repr(e)}")
            return False

    @classmethod
    def get_users(cls):
        url = f"{cls.url}/users"

        try:
            response = requests.get(
                url,
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("users", [])
            else:
                logger.error(f"get users - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_users {repr(e)}")

        return []

    @classmethod
    def get_user_data(cls):
        url = f"{cls.url}/users/me"

        try:
            response = requests.get(
                url,
                json={
                    "user_id": cls.user_id
                },                  
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },   
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()

                user_data = data.get("user_data", None)
                if not user_data:
                    return user_data

                if user_data.get("profile"):
                    profile = json.loads(user_data["profile"])
                    user_data.pop("profile")
                    user_data["profile"] = profile

                return user_data
            else:
                logger.error(f"failed to get user data - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get user data {repr(e)}")

        return {} 
    
    @classmethod
    def update_user_data(cls, data: dict):
        url = f"{cls.url}/users/me"

        try:
            response = requests.patch(
                url,
                json={
                    "user_id": cls.user_id,
                    "user_data": data
                },                 
                headers = {
                    "Authorization": f"Bearer {cls.access_token}",
                    "Content-Type": "application/json"
                },                                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code in (200, 204):
                return True
            else:
                logger.error(f"failed to update user data {response.status_code} {response.reason}")
                return False

        except Exception as e:
            logger.error(f"failed to update user data {repr(e)}")
            return False    

    @classmethod
    def get_contacts(cls):
        url = f"{cls.url}/contacts"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },   
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("contacts", [])
            else:
                logger.error(f"get contacts - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_contacts {repr(e)}")

        return []

    @classmethod
    def create_contact(cls) -> int:
        url = f"{cls.url}/contacts"

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:                
                data = response.json()
                return data.get("contact_id", -1)
            else:
                logger.error(f"create contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to create_contact {repr(e)}")

        return -1    
    
    @classmethod
    def update_contact(cls, contact_id: int, data: dict):
        url = f"{cls.url}/contacts/{contact_id}"

        try:
            response = requests.patch(
                url,
                json={
                    "contact_data": data
                },                 
                headers = {
                    "Authorization": f"Bearer {cls.access_token}",
                    "Content-Type": "application/json"
                },                                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code in (200, 204):
                return True
            else:
                logger.error(f"update contact - {response.status_code} {response.reason}")
                return False

        except Exception as e:
            logger.error(f"failed to update_contact {repr(e)}")
            return False

    @classmethod
    def get_contact(cls, contact_id: int):
        url = f"{cls.url}/contact/{contact_id}"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },   
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("contact", {})
            else:
                logger.error(f"get contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_contact {repr(e)}")

        return {} 

    @classmethod
    def create_user(cls, user_name, user_passwd) -> int:
        url = f"{cls.url}/users"

        try:
            response = requests.post(
                url,
                json={
                    "user_name": user_name,
                    "user_passwd": user_passwd
                },                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("user_id", -1)
            else:
                logger.error(f"create user - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to create_user {repr(e)}")

        return -1

    @classmethod
    def create_conversation(cls, contact_id: int) -> int:
        url = f"{cls.url}/conversations"

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },                
                json={
                    "contact_id": contact_id
                },                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:                
                data = response.json()
                return data.get("conversation_id", -1)
            else:
                logger.error(f"create conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to create_conversation {repr(e)}")

        return -1     

    @classmethod
    def delete_conversation(cls, conversation_id: int):
        url = f"{cls.url}/conversations/{conversation_id}"

        try:
            response = requests.delete(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code != 200:                
                logger.error(f"delete_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to delete_conversation {repr(e)}")

    @classmethod
    def delete_contact(cls, contact_id: int):
        url = f"{cls.url}/contacts/{contact_id}"

        try:
            response = requests.delete(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code != 200:                
                logger.error(f"delete_contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to delete_contact {repr(e)}")

    @classmethod
    def get_conversations(cls, contact_id):
        url = f"{cls.url}/contacts/{contact_id}/conversations"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("conversations", [])
            else:
                logger.error(f"get_conversations - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_conversations {repr(e)}")

        return []      

    @classmethod
    def get_conversation(cls, conversation_id):
        url = f"{cls.url}/conversations/{conversation_id}"

        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {cls.access_token}"
                },
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("conversation")
            else:
                logger.error(f"get_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_conversation {repr(e)}")

        return None

    @classmethod
    def get_messages(cls, conversation_id: int, max_message: int = 100):
        url = f"{cls.url}/conversations/{conversation_id}/messages"

        request = GetMessagesRequest(
            max_message=max_message
        )

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },
                json=request.model_dump(),
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            else:
                logger.error(f"failed to get messages {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get messages {repr(e)}")

        return []

    @classmethod
    def get_attachments(cls, message_id):
        url = f"{cls.url}/messages/{message_id}/attachments"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("attachments", [])
            else:
                logger.error(f"failed to get attachments {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get attachments {repr(e)}")

        return []

    @classmethod
    def login_user(cls, user_name, user_passwd) -> bool:
        url = f"{cls.url}/login"
        cls.access_token = ""
        cls.user_name = ""

        try:
            response = requests.post(
                url,
                json={
                    "user_name": user_name,
                    "user_passwd": user_passwd
                },                
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                cls.access_token = data.get("access_token", "")
                asyncio.create_task(cls._on_login_success(cls.access_token))
                cls.user_id = data.get("user_id", -1)
                cls.user_name = user_name
                return True
            else:
                logger.error(f"login failed {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"login failed {repr(e)}")

        return False

    @classmethod
    def get_model(cls, model_name: str, model_path: Path):
        url = f"{cls.url}/models/{model_name}/url"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {cls.access_token}"
                },
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                sources = data.get("model_urls", [])

                logger.debug(f"found sources {sources}")

                for source in sources:
                    cls.download(
                        url=source,
                        download_path=model_path,
                        asynchronous=False
                    )
                
            else:
                logger.error(f"get_model - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_model {repr(e)}")
