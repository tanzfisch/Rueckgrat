import os
import requests
import certifi
from urllib.parse import urlparse
import asyncio
import json
from pathlib import Path
from typing import Callable, Optional

from app.common import get_logger, DownloadQueue, ChatRequest, GetMessagesRequest, WebSocketClient
logger = get_logger()

class Hub:
    user_id = -1
    user_name = ""
    access_token = ""
    nsfw_allowed = False
    download_queue = DownloadQueue()
    ws_task = None
    websocket_client = None
    _last_health: Optional[str] = None

    @classmethod
    def init(cls, config):
        cls.config = config
        
        cls.url = f"https://{cls.config.host}:{cls.config.port}"
        cls.uri = f"wss://{cls.config.host}:{cls.config.port}/ws"            

        name = "rueckgrat-caddy.cert"
        assets = os.getenv("FLET_ASSETS_DIR")
        paths = [
            *( [Path(assets) / name] if assets else [] ),
            Path.home() / ".ssh" / name,
        ]

        cert = next((p for p in paths if p.exists()), None)
        if not cert:
            # no caddy cert: fall back to the public CAs (works through cloudflare),
            # instead of False, which turned verification off
            cls.server_cert = certifi.where()
            logger.error(f"failed to get certificate from hub, using public CAs only")
        else:
            cls.server_cert = cls._build_ca_bundle(cert)

        logger.info(f"hub: {cls.url}")
        logger.info(f"hub ws: {cls.uri}")
        logger.info(f"hub cert: {cls.server_cert}")

        cls.websocket_client = WebSocketClient(cls.uri, cls.server_cert)

    @classmethod
    def _build_ca_bundle(cls, caddy_cert: Path) -> str:
        """public CAs + our caddy root in one PEM file, so both cloudflare and direct caddy connections verify"""
        cache_dir = Path(os.getenv("FLET_APP_STORAGE_CACHE") or Path.home() / ".cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        bundle = cache_dir / "rueckgrat-ca-bundle.pem"
        public = Path(certifi.where()).read_text()
        caddy = Path(caddy_cert).read_text()
        bundle.write_text(public.rstrip() + "\n" + caddy)
        return str(bundle)

    @classmethod
    def get_user_name(cls):
        return cls.user_name

    @classmethod
    def shutdown(cls):
        cls.download_queue.stop()

    @classmethod
    def download_file(cls, image_path: str, download_path: str, max_retry: int = 5):
        url = f"{cls.url}/downloads/{image_path}"
        cls.download(url, download_path, max_retry=max_retry)

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
    def _on_login_success(cls, token: str):
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
    async def logout(cls):
        """
        Forgets the session and closes the websocket. The hub keeps no sessions,
        so there is nothing to tell it, the token is simply dropped.
        """
        await cls.stop_websocket()
        if cls.websocket_client:
            await cls.websocket_client.close()

        logger.info(f"logged out {cls.user_name} id:{cls.user_id}")
    
        cls.access_token = ""
        cls.user_id = -1
        cls.user_name = ""
        cls.nsfw_allowed = False

    @classmethod
    async def _start_websocket(cls, token: str):
        await cls.websocket_client.connect(token)

    @classmethod
    def unregister_incomming_message(cls, callback: Callable[[dict], None]):
        cls.websocket_client.unregister_incomming_message(callback)

    @classmethod
    def register_incomming_message(cls, callback: Callable[[dict], None]):
        cls.websocket_client.register_incomming_message(callback)

    @classmethod
    def chat(cls, contact_id: int, conversation_id: int, role: str, user_role_name: str, content: str, temperature: float):
        chat_request = ChatRequest(
            contact_id=contact_id,
            conversation_id=conversation_id,
            role=role,
            name=user_role_name,
            content=content,
            temperature=temperature
        )
        payload = {"chat": chat_request.model_dump()}
        cls.websocket_client.send_message(json.dumps(payload))

    @classmethod
    def generate(cls, prompt: dict):
        payload = {"generate": prompt}
        cls.websocket_client.send_message(json.dumps(payload))    

    @classmethod
    def check_health(cls):
        """returns True when everything is up. only logs when the state changes"""
        url = f"{cls.url}/health"
        try:
            response = requests.get(url, timeout=30, verify=cls.server_cert)
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "error")
                message = data.get("message", "")
            else:
                status, message = "unreachable", f"http {response.status_code}"
        except Exception as e:
            status, message = "unreachable", repr(e)

        if status != cls._last_health:
            if status == "ok":
                pass  # success is silent
            elif status == "degraded":
                logger.warning(f"some nodes not connected: {message}")
            elif status == "unreachable":
                logger.error(f"hub not reachable: {message}")
            else:
                logger.error(f"system unhealthy: {message}")
            cls._last_health = status

        return status == "ok"

    @classmethod
    def set_log_level(cls, level):
        url = f"{cls.url}/log-level/{level}"
        try:
            response = requests.put(url, timeout=5, verify=cls.server_cert)
            if response.status_code == 200:
                return True
            logger.error(f"failed to set log level - {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"failed to set log level: {repr(e)}")
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
                logger.error(f"failed to update contact: {response.status_code} {response.reason}")
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
    def get_signup_mode(cls) -> str:
        """
        Returns "open" or "invite". Falls back to "invite" if the hub can't tell,
        an invite hub then still rejects the signup with a clear message.
        """
        url = f"{cls.url}/signup-mode"

        try:
            response = requests.get(url, timeout=10, verify=cls.server_cert)
            if response.status_code == 200:
                return response.json().get("mode", "open")
            logger.error(f"get signup mode - {response.status_code} {response.reason}")
        except Exception as e:
            logger.error(f"failed to get_signup_mode {repr(e)}")

        return "invite"

    @classmethod
    def create_user(cls, user_name, user_passwd, invite_token: str | None = None, email: str | None = None) -> tuple[int, str | None]:
        """
        Returns (user_id, None) on success or (-1, error message for the user).
        """
        url = f"{cls.url}/users"

        body = {
            "user_name": user_name,
            "user_passwd": user_passwd
        }
        if invite_token:
            body["invite_token"] = invite_token
        if email:
            body["email"] = email

        try:
            response = requests.post(
                url,
                json=body,
                timeout=10,
                verify=cls.server_cert,
            )

            if response.status_code == 200:
                data = response.json()
                user_id = data.get("user_id")
                if user_id is None:
                    return -1, "username already exists"
                return user_id, None

            logger.error(f"create user - {response.status_code} {response.reason}")
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            return -1, detail if isinstance(detail, str) else f"signup failed ({response.status_code})"

        except Exception as e:
            logger.error(f"failed to create_user {repr(e)}")
            return -1, "could not reach the hub"

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
    def delete_conversation(cls, conversation_id: int) -> list[str]:
        """returns the images the hub released with the conversation (nobody else uses them), [] on failure"""
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

            if response.status_code == 200:
                return response.json().get("released_images", [])
            else:
                logger.error(f"delete_conversation - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to delete_conversation {repr(e)}")

        return []

    @classmethod
    def delete_contact(cls, contact_id: int) -> list[str]:
        """returns the images the hub released with the contact (nobody else uses them), [] on failure"""
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

            if response.status_code == 200:
                return response.json().get("released_images", [])
            else:
                logger.error(f"delete_contact - {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"failed to delete_contact {repr(e)}")

        return []

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
        cls.nsfw_allowed = False

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
                cls._on_login_success(cls.access_token)
                cls.user_id = data.get("user_id", -1)
                cls.user_name = user_name
                cls.nsfw_allowed = bool(data.get("nsfw_allowed", False))
                return True
            else:
                logger.error(f"login failed {response.status_code} {response.reason}")

        except Exception as e:
            logger.error(f"login failed {repr(e)}")

        return False

    @classmethod
    def tts(cls, text: str, voice: str = "") -> Optional[bytes]:
        """ask the hub to speak text, returns wav bytes or None"""
        try:
            response = requests.post(
                f"{cls.url}/tts",
                json={"text": text, "voice": voice},
                headers={"Authorization": f"Bearer {cls.access_token}"},
                timeout=240,
                verify=cls.server_cert,
            )
            if response.status_code == 200:
                return response.content
            logger.error(f"tts - {response.status_code} {response.reason}")
        except Exception as e:
            logger.error(f"failed to tts {repr(e)}")
        return None

    @classmethod
    def upload_voice(cls, wav: bytes | str | Path, gender: str = "") -> Optional[str]:
        """uploads a wav voice sample to the hub, returns the voice uuid or None"""
        try:
            data = wav if isinstance(wav, bytes) else Path(wav).read_bytes()
        except Exception as e:
            logger.error(f"failed to read voice file {repr(e)}")
            return None

        try:
            response = requests.post(
                f"{cls.url}/voices",
                data=data,
                params={"gender": gender} if gender else None,
                headers={
                    "Authorization": f"Bearer {cls.access_token}",
                    "Content-Type": "audio/wav"
                },
                timeout=60,
                verify=cls.server_cert,
            )
            if response.status_code == 200:
                voice_id = response.json().get("voice_id")
                logger.debug(f"uploaded voice. got id {voice_id}")
                return voice_id
            logger.error(f"upload_voice - {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"failed to upload_voice {repr(e)}")
        return None

    @classmethod
    def get_predefined_voices(cls) -> list:
        """the voices that come with rueckgrat, each with id, name, description, gender and language"""
        try:
            response = requests.get(
                f"{cls.url}/voices/predefined",
                headers={"Authorization": f"Bearer {cls.access_token}"},
                timeout=10,
                verify=cls.server_cert,
            )
            if response.status_code == 200:
                return response.json().get("voices", [])
            logger.error(f"get_predefined_voices - {response.status_code} {response.reason}")
        except Exception as e:
            logger.error(f"failed to get_predefined_voices {repr(e)}")
        return []

    @classmethod
    def use_predefined_voice(cls, predefined_id: str) -> Optional[str]:
        """lets the hub copy a predefined voice to the user's voices, returns the voice uuid or None"""
        try:
            response = requests.post(
                f"{cls.url}/voices/predefined/{predefined_id}",
                headers={"Authorization": f"Bearer {cls.access_token}"},
                timeout=60,
                verify=cls.server_cert,
            )
            if response.status_code == 200:
                voice_id = response.json().get("voice_id")
                logger.debug(f"using predefined voice {predefined_id}. got id {voice_id}")
                return voice_id
            logger.error(f"use_predefined_voice - {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"failed to use_predefined_voice {repr(e)}")
        return None

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
