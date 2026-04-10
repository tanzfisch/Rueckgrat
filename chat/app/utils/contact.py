import json
from common import Logger
logger = Logger(__name__).get_logger()

class Contact:
    def __init__(self, data: dict):
        self.data = data

    def get_id(self) -> int:
        return self.data["id"]

    def get_name(self) -> str:
        return self.data["name"]

    def get_role(self) -> str:
        return self.data["role"]

    def get_persona(self) -> str:
        return self.data["persona"]

    def get_gender(self) -> str:
        return self.data["gender"]

    def get_voice_model(self) -> str:
        return self.data.get("piper_voice_model", None)

    def get_llm_temperature(self) -> float:
        return self.data["profile"]["llm_parameters"]["temperature"]

    def get_latest_profile_image_name(self) -> str:
        images = self.data["images"]
        if not images:
            return ""
        
        profile_images = [img for img in images if img['type'] == 'profile']
        if not profile_images:
            return None
        latest = max(profile_images, key=lambda img: img['created_at'])
        return latest["file_key"]