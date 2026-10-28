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

    def get_voice_id(self) -> str:
        return Utils.get_nested_value(
            self.data, ["profile", "tts_parameters", "voice_id"], ""
        )

    def get_llm_temperature(self) -> float:
        return Utils.get_nested_value(
            self.data, ["profile", "llm_parameters", "temperature"], 0.7
        )

    def get_latest_profile_image_name(self) -> str:
        images = Utils.get_nested_value(self.data, ["images"], [])
        if not images:
            logger.warning("no images in this profile")
            return ""

        profile_images = [img for img in images if img.get("type") == "profile"]
        if not profile_images:
            logger.error("no profile image in this profile")
            return ""
        # the id breaks a tie: an image set within the same second as the last one
        latest = max(profile_images, key=lambda img: (img.get("created_at", ""), img.get("id", 0)))
        return latest.get("file_key", "")