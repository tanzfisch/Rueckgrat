import os
import requests
import asyncio
import json
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
from app.utils.websocket import WebSocketClient
from typing import Callable, Optional
import configparser

from PySide6.QtCore import QThread, QObject, Signal

import logging
logger = logging.getLogger(__name__)

class Backend:
    _instance = None

    def __init__(self):
        config = configparser.ConfigParser()
        config_path = Path("~/.config/Rueckgrat/rueckgrat.conf").expanduser()
        logging.info(f"reading config from {config_path}")

        with open(config_path, encoding="utf-8-sig") as f:
            config.read_file(f)

        self.host = config.get('chat', 'rueckgrat_hub_host', fallback="localhost")
        self.port = config.get('chat', 'rueckgrat_hub_port', fallback="443")
        self.verify = config.get('chat', 'server_cert', fallback="no")

        self.url = f"https://{self.host}:{self.port}"
        self.uri = f"wss://{self.host}:{self.port}/ws"
        self.access_token = ""

        self.on_incomming_message: Optional[Callable[[str], None]] = None

        logging.info(f"using backend at {self.url}")
        logging.info(f"websocket at {self.uri}")
        logging.info(f"server_cert {self.verify}")

        if self.verify == "no":
            self.verify = False
            logging.warning('No server certificate found. Connection will be insecure')

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start_websocket(self):
        self.websocket_client = WebSocketClient(self.uri)
        self.websocket_client.set_on_message(self._on_incomming_websocket)
        await self.websocket_client.connect()

    def async_chat(self, contact_id: int, conversation_id: int, role: str, content: str, temperature: float):
        payload={
            "chat": {
                "contact_id": contact_id,
                "conversation_id": conversation_id,
                "role": role,
                "name": self.user_name,
                "content": content,
                "temperature": temperature
            }         
        }    
        asyncio.get_event_loop().create_task(Backend.get_instance()._send_async_chat(json.dumps(payload)))

    async def _send_async_chat(self, payload):
        await self.websocket_client.send_message(payload)

    def _on_incomming_websocket(self, text):
        if self.on_incomming_message:
            self.on_incomming_message(text)

    def set_on_incomming_message(self, callback: Callable[[str], None]):
        self.on_incomming_message = callback

    def check_health(self):
        url = f"{self.url}/health"

        try:
            response = requests.get(url, timeout=3, verify=self.verify)

            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "error")
                if status == "error":
                    message = data.get("message", "")
                    logging.error(f"failed to check health of the system: {message}")
                    return False

                logging.debug("system is healthy")
                return True
            else:
                logging.error(f"lost connection to hub - {response.status_code} {response.reason}")
                return False
                            
        except Exception:
            logging.error("failed to get health response from backend due to an exception")
            return False   

    def get_users(self):
        url = f"{self.url}/users"

        try:
            response = requests.get(
                url,
                timeout=10,
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("users", [])
            else:
                logging.error(f"get users - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_users {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("contacts", [])
            else:
                logging.error(f"get contacts - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_contacts {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:                
                data = response.json()
                return data.get("contact_id", -1)
            else:
                logging.error(f"create contact - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to create_contact {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code in (200, 204):
                return True
            else:
                logging.error(f"update contact - {response.status_code} {response.reason}")
                return False

        except Exception as e:
            logging.error(f"failed to update_contact {repr(e)}")
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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("contact", {})
            else:
                logging.error(f"get contact - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_contact {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("user_id", -1)
            else:
                logging.error(f"create user - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to create_user {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:                
                data = response.json()
                return data.get("conversation_id", -1)
            else:
                logging.error(f"create conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to create_conversation {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code != 200:                
                logging.error(f"delete_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to delete_conversation {repr(e)}")
    
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
                verify=self.verify,
            )

            if response.status_code != 200:                
                logging.error(f"delete_contact - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to delete_contact {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("conversations", [])
            else:
                logging.error(f"get_conversations - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_conversations {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("conversation")
            else:
                logging.error(f"get_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_conversation {repr(e)}")

        return None

    def update_conversation(self, conversation_id: int, brief: str, context: str):
        url = f"{self.url}/update_conversation"

        try:
            response = requests.patch(
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "conversation_id": conversation_id,
                    "brief": brief,
                    "context": context
                },
                timeout=10,
                verify=self.verify,
            )

            if response.status_code in (200, 204):
                return True
            else:
                logging.error(f"update_conversation - {response.status_code} {response.reason}")
                return False

        except Exception as e:
            logging.error(f"failed to update_conversation {repr(e)}")
            return False

    def get_messages(self, conversation_id):
        url = f"{self.url}/messages"

        try:
            response = requests.get(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },
                json={
                    "conversation_id": conversation_id
                },                  
                timeout=10,
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            else:
                logging.error(f"get_messages - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_messages {repr(e)}")

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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token", "")
                return self.access_token
            else:
                logging.error(f"login_user - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to login_user {repr(e)}")

        return ""

    def _download_file(self, url, filepath):
        if os.path.exists(filepath):
            return
        
        r = requests.get(url, stream=True)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))

        with open(filepath, "wb") as f:
            with tqdm(total=total_size, unit="B", unit_scale=True, desc=f"Downloading {url}", unit_divisor=1024) as pbar:
                for chunk in r.iter_content(chunk_size=64*1024):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

    def _download_from_url(self, url: str, install_path: str, force_download: bool=False):
        target_dir = Path("data/models") / install_path
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = os.path.basename(urlparse(url).path)
        target_file = target_dir / filename

        if force_download and os.path.exists(target_file):
            target_file.unlink(missing_ok=True)

        self._download_file(url, target_file)

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
                verify=self.verify,
            )

            if response.status_code == 200:
                data = response.json()
                sources = data.get("model_urls", [])
                for source in sources:
                    self._download_from_url(source, Path(model_name))
                
            else:
                logging.error(f"get_model - {response.status_code} {response.reason}")

        except Exception as e:
            logging.error(f"failed to get_model {repr(e)}")
