from app.common import get_logger, Utils
logger = get_logger()

class Contact:
    def __init__(self, data: dict):
        self.data = data

    def get_id(self) -> int:
        return Utils.get_nested_value(self.data, ["id"], 0)

    def get_name(self) -> str:
        return Utils.get_nested_value(self.data, ["name"], "")

    def get_role(self) -> str:
        return Utils.get_nested_value(self.data, ["role"], "")

    def get_persona(self) -> str:
        return Utils.get_nested_value(self.data, ["personality"], "")

    def get_gender(self) -> str:
        return Utils.get_nested_value(self.data, ["gender"], "")

    def get_voice_model(self) -> str:
        return Utils.get_nested_value(
            self.data, ["profile", "tts_parameters", "piper_voice_model"], ""
        )

    def get_llm_temperature(self) -> float:
        return Utils.get_nested_value(
            self.data, ["profile", "llm_parameters", "temperature"], 0.7
        )

    def get_latest_profile_image_name(self) -> str:
        images = Utils.get_nested_value(self.data, ["images"], [])
        if not images:
            logger.error("no images in this profile")
            return ""

        profile_images = [img for img in images if img.get("type") == "profile"]
        if not profile_images:
            logger.error("no profile image in this profile")
            return ""
        latest = max(profile_images, key=lambda img: img.get("created_at", ""))
        return latest.get("file_key", "")