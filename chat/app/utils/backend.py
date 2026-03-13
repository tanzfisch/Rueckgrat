import os
import requests
import asyncio
import json
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
from app.utils import Settings
from app.utils.websocket import WebSocketClient
from typing import Callable, Optional

class Backend:
    def __init__(self):
        self.host = Settings.get_value("backend_host", "localhost")
        self.port = Settings.get_value("backend_port", "443")
        self.server_cert=Settings.get_value("server_cert", "/var/www/html/rueckgrad_backend.crt")

        self.url = f"https://{self.host}:{self.port}"
        self.uri = f"wss://{self.host}:{self.port}/ws"
        self.access_token = ""

        self.on_incomming_message: Optional[Callable[[str], None]] = None

        print(f"using backend at {self.url}")
        print(f"websocket at {self.uri}")
        print(f"using cert from {self.server_cert}")

    async def start_websocket(self):
        self.websocket_client = WebSocketClient(self.uri)
        self.websocket_client.set_on_message(self._on_incomming_websocket)
        await self.websocket_client.connect()

    def async_chat(self, contact_id: int, conversation_id: int, role: str, content: str):
        payload={
            "chat": {
                "contact_id": contact_id,
                "conversation_id": conversation_id,
                "role": role, 
                "content": content
            }
        }        
        asyncio.get_event_loop().create_task(backend._send_async_chat(json.dumps(payload)))

    async def _send_async_chat(self, payload):
        await self.websocket_client.send_message(payload)

    def _on_incomming_websocket(self, text):
        if self.on_incomming_message:
            self.on_incomming_message(text)

    def set_on_incomming_message(self, callback: Callable[[str], None]):
        self.on_incomming_message = callback

    def chat(self, contact_id: int, conversation_id: int, role: str, content: str):
        url = f"{self.url}/chat"

        payload={
            "contact_id": contact_id,
            "conversation_id": conversation_id,
            "role": role, 
            "content": content
        }        

        try:
            response = requests.post(
                url,
                headers = {
                    "Authorization": f"Bearer {self.access_token}"
                },
                json=payload,
                timeout=20,
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                reply = data.get("content", "")
                return "assistant", reply

        except Exception as e:
            print(f"Error: failed to get a chat response {repr(e)}")

        return "error", "Error: failed to get chat response from backend"

    def check_health(self):
        url = f"{self.url}/health"

        try:
            response = requests.get(url, timeout=3, verify=self.server_cert)

            if response.status_code == 200 and response.json() == {"status": "ok"}:
                return True
            else:
                print(f"Error: {response.status_code} {response.reason}")
                return False
                            
        except Exception:
            print("Error: failed to get health response from backend due to an exception")
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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to get_users {repr(e)}")

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to get_contacts {repr(e)}")

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to create_contact {repr(e)}")

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
                    "Authorization": f"Bearer {self.access_token}"
                },                                
                timeout=10,
                verify=self.server_cert,
            )

            if response.status_code != 200:
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to update_contact {repr(e)}")
    
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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to get_contact {repr(e)}")

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to create_user {repr(e)}")

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to create_conversation {repr(e)}")

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to delete_conversation {repr(e)}")
    
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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to delete_contact {repr(e)}")

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to get_conversations {repr(e)}")

        return []      

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
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            else:
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to get_messages {repr(e)}")

        return []          

    def login_user(self, user_name, user_passwd):
        url = f"{self.url}/login"
        self.access_token = ""

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
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to login_user {repr(e)}")

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
        target_dir = Path("models") / install_path
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
                verify=self.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                sources = data.get("model_urls", [])
                for source in sources:
                    self._download_from_url(source, Path(model_name))
                
            else:
                print(f"Error: {response.status_code} {response.reason}")

        except Exception as e:
            print(f"Error: failed to get_model {repr(e)}")
    
backend = Backend()