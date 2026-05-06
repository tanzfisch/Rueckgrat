import os
import requests
import asyncio
import json
from pathlib import Path
from app.utils.websocket import WebSocketClient
from typing import Callable, List
from .config import RueckgratConfig

from common import Logger, DownloadQueue, ChatRequest, GetMessagesRequest
logger = Logger(__name__).get_logger()

class Backend:
    _instance = None

    def __init__(self):
        logger.debug("Backend init")
        self.config = RueckgratConfig()

        self.server_cert = self.config.server_cert

        self.url = f"https://{self.config.host}:{self.config.port}"
        self.uri = f"wss://{self.config.host}:{self.config.port}/ws"
        self.access_token = ""        

        logger.info(f"using backend at {self.url}")
        logger.info(f"websocket at {self.uri}")
        logger.info(f"server_cert {self.server_cert}")

        if self.server_cert == "no":
            self.server_cert = False
            logger.warning('No server certificate found. Connection will be insecure')

        self.on_incoming_message: List[Callable[[dict], None]] = []

        self.download_queue = DownloadQueue()

    def shutdown(self):
        self.download_queue.stop()

    def download(self, source_path: str, download_path: str, max_retry: int = 5):
        url = f"{self.url}/download/{source_path}"
        self.download_queue.add(url, download_path, self.access_token, self.server_cert, max_retry)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start_websocket(self):
        self.websocket_client = WebSocketClient(self.uri, self.server_cert)
        self.websocket_client.set_on_message(self._on_incomming_websocket)
        await self.websocket_client.connect()

    def async_chat(self, contact_id: int, conversation_id: int, role: str, content: str, temperature: float):
         
        chat_request = ChatRequest(
            contact_id=contact_id,
            conversation_id=conversation_id,
            role=role,
            name=self.user_name,
            content=content,
            temperature=temperature
        )

        payload={
            "chat": chat_request.model_dump()
        }    
        asyncio.get_event_loop().create_task(Backend.get_instance()._send_async_chat(json.dumps(payload)))

    async def _send_async_chat(self, payload):
        await self.websocket_client.send_message(payload)

    def _on_incomming_websocket(self, msg: dict):
        try:
            for func in self.on_incoming_message:
                func(msg)
        except Exception as e:
            logger.error(f"failed to handle incomming message: {repr(e)}")

    def unregister_incomming_message(self, callback: Callable[[dict], None]):
        self.on_incoming_message.remove(callback)

    def register_incomming_message(self, callback: Callable[[dict], None]):
        self.on_incoming_message.append(callback)

    def check_health(self):
        url = f"{self.url}/health"

        try:
            response = requests.get(
                url, 
                timeout=9, 
                verify=self.server_cert
            )

            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "error")
                if status == "error":
                    message = data.get("message", "")
                    logger.error(f"failed to check health of the system: {message}")
                    return False

                logger.debug("system is healthy")
                return True
            else:
                logger.error(f"lost connection to hub - {response.status_code} {response.reason}")
                return False
                            
        except Exception as e:
            logger.error(f"failed health check with: {repr(e)}")
            return False   

    def get_users(self):
        url = f"{self.url}/users"

        try:
            response = requests.get(
                url,
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("users", [])
            else:
                logger.error(f"get users - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_users {repr(e)}")

        return []

    def get_contacts(self):
        url = f"{self.url}/contacts"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },   
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("contacts", [])
            else:
                logger.error(f"get contacts - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_contacts {repr(e)}")

        return []

    def create_contact(self) -> int:
        url = f"{self.url}/contact"

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:                
                data = response.json()
                return data.get("contact_id", -1)
            else:
                logger.error(f"create contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to create_contact {repr(e)}")

        return -1          
    
    def update_contact(self, contact_id: int, data: dict):
        url = f"{self.url}/update_contact"

        try:
            response = requests.post(
                url,
                json={
                    "contact_id": contact_id,
                    "contact_data": data
                },                 
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },                                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code in (200, 204):
                return True
            else:
                logger.error(f"update contact - {response.status_code} {response.reason}")
                return False

        except Exception as e:
            logger.error(f"failed to update_contact {repr(e)}")
            return False
    
    def get_contact(self, contact_id: int):
        url = f"{self.url}/contact"

        try:
            response = requests.get(
                url,
                json={
                    "contact_id": contact_id
                },                  
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },   
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("contact", {})
            else:
                logger.error(f"get contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_contact {repr(e)}")

        return {} 

    def create_user(self, user_name, user_passwd) -> int:
        url = f"{self.url}/users"

        try:
            response = requests.post(
                url,
                json={
                    "user_name": user_name,
                    "user_passwd": user_passwd
                },                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("user_id", -1)
            else:
                logger.error(f"create user - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to create_user {repr(e)}")

        return -1
    
    def create_conversation(self, contact_id: int) -> int:
        url = f"{self.url}/conversations"

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },                
                json={
                    "contact_id": contact_id
                },                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:                
                data = response.json()
                return data.get("conversation_id", -1)
            else:
                logger.error(f"create conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to create_conversation {repr(e)}")

        return -1     
    
    def delete_conversation(self, conversation_id: int):
        url = f"{self.url}/delete_conversation"

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },                
                json={
                    "conversation_id": conversation_id
                },                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code != 200:                
                logger.error(f"delete_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to delete_conversation {repr(e)}")
    
    def delete_contact(self, contact_id: int):
        url = f"{self.url}/delete_contact"

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },                
                json={
                    "contact_id": contact_id
                },                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code != 200:                
                logger.error(f"delete_contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to delete_contact {repr(e)}")

    def get_conversations(self, contact_id):
        url = f"{self.url}/conversations"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },
                json={
                    "contact_id": contact_id
                },                  
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("conversations", [])
            else:
                logger.error(f"get_conversations - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_conversations {repr(e)}")

        return []      

    def get_conversation(self, conversation_id):
        url = f"{self.url}/get_conversation"

        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}"
                },
                json={
                    "conversation_id": conversation_id
                },
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("conversation")
            else:
                logger.error(f"get_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_conversation {repr(e)}")

        return None

    def get_messages(self, conversation_id: int, max_message: int = 100):
        url = f"{self.url}/messages"

        request = GetMessagesRequest(
            conversation_id=conversation_id, 
            max_message=max_message
        )

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },
                json=request.model_dump(),
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            else:
                logger.error(f"failed to get messages {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get messages {repr(e)}")

        return []

    def get_attachments(self, message_id):
        url = f"{self.url}/attachments"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },
                json={
                    "message_id": message_id
                },                  
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("attachments", [])
            else:
                logger.error(f"failed to get attachments {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get attachments {repr(e)}")

        return []

    def login_user(self, user_name, user_passwd):
        url = f"{self.url}/login"
        self.access_token = ""
        self.user_name=user_name

        try:
            response = requests.post(
                url,
                json={
                    "user_name": user_name,
                    "user_passwd": user_passwd
                },                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token", "")
                return self.access_token
            else:
                logger.error(f"login_user - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to login_user {repr(e)}")

        return ""

    def get_model(self, model_name):
        url = f"{self.url}/model"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },
                json={
                    "model_name": model_name
                },                  
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                sources = data.get("model_urls", [])
                for source in sources:
                    self.download(source, Path(model_name)) # TODO
                
            else:
                logger.error(f"get_model - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to get_model {repr(e)}")
