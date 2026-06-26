from app.common import get_logger, Utils
logger = get_logger()

class Contact:
    def __init__(self, data: dict):
        self.data = data

    def get_id(self) -> int:
        return Utils.get_nested_value(self.data, ["id"], None)

    def get_name(self) -> str:
        return Utils.get_nested_value(self.data, ["name"], None)

    def get_role(self) -> str:
        return Utils.get_nested_value(self.data, ["role"], None)

    def get_persona(self) -> str:
        return Utils.get_nested_value(self.data, ["personality"], None)

    def get_gender(self) -> str:
        return Utils.get_nested_value(self.data, ["gender"], None)

    def get_voice_model(self) -> str:
        return Utils.get_nested_value(self.data, ["profile", "tts_parameters", "piper_voice_model"], None)

    def get_llm_temperature(self) -> float:
        return Utils.get_nested_value(self.data, ["profile", "llm_parameters", "temperature"], None)

    def get_latest_profile_image_name(self) -> str:
        images = Utils.get_nested_value(self.data, ["images"], None)
        if not images:
            logger.error("no images in this profile")
            return None
        
        profile_images = [img for img in images if img['type'] == 'profile']
        if not profile_images:
            logger.error("no profile image in this profile")
            return None
        latest = max(profile_images, key=lambda img: img['created_at'])
        return latest["file_key"]