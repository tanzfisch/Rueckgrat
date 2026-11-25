import json
from typing import Dict, Any
from enum import Enum

from . import prompts

from app.common import get_logger, Utils, IMAGE_STYLES, DEFAULT_IMAGE_STYLE
logger = get_logger()

class ImageType(Enum):
    Portrait = 1
    UpperBody = 2
    FullBody = 3

class ContactImagePromptCompiler:
    def __init__(self, contact: Dict[str, Any], user_data: Dict[str, Any], context: Dict[str, Any] = None, 
                 image_type: ImageType = ImageType.FullBody, show_assistant: bool = True, show_user: bool = False, 
                 use_facial_features: bool = True, prompt: str = None):
        self.contact = contact
        self.user_data = user_data
        self.profile = contact.get("profile", {})
        self.image_type = image_type
        self.show_assistant = show_assistant
        self.show_user = show_user        
        self.prompt = prompt
        self.context = context        
        self.use_facial_features = use_facial_features

        if not self.context:
            logger.warning("got no context yet")

    def _build_location(self) -> str:
        try:
            if self.context:
                return Utils.get_nested_value(self.context, ["location"], "")
            else:
                return Utils.get_nested_value(self.profile, ["profile_picture_context", "location"], "")
        except Exception as e:
            logger.error(f"failed to build location {repr(e)}")

    def _build_topic(self) -> str:
        try:
            if self.context:
                return Utils.get_nested_value(self.context, ["topic"], "")
            else:
                return Utils.get_nested_value(self.profile, ["profile_picture_context", "topic"], "")
        except Exception as e:
            logger.error(f"failed to build topic {repr(e)}")

    def _clothing(self, source: Dict[str, Any], path: list) -> str:
        def text(field: str) -> str:
            value = Utils.get_nested_value(source, path[:-1] + [field], "")
            return value.strip() if isinstance(value, str) else ""

        upper, lower = text("upper_body"), text("body")

        if path[-1] == "body":
            return lower

        # never on a safe-for-work contact (same check as prompt_compiler.py)
        if str(self.profile.get("sfw", "")).lower() == "sfw":
            return upper

        if not upper and not lower:
            return "naked"
        if not upper:
            return "bare upper body"
        if not lower:
            return f"{upper}, naked below the waist"
        return upper

    def _build_people(self) -> str:
        try:
            assistant_stack = []
            user_stack = []

            # portrait
            if self.image_type == ImageType.Portrait or self.image_type == ImageType.UpperBody or self.image_type == ImageType.FullBody:            
                # skip everything that could be derived from a reference image (FaceID of that person)
                if self.use_facial_features:
                    assistant_stack.append(Utils.get_nested_value(self.contact, ["identity", "gender"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "general"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "hair"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "face"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "skin"], ""))

                # only needed when the user is in the picture. a new user has no user data yet.
                # when the reference is the user, skip gender too: FaceID already provides identity
                if self.show_user and self.user_data and self.use_facial_features:
                    user_profile = json.loads(self.user_data["profile"])
                    user_gender = Utils.get_nested_value(user_profile, ["gender"], "")
                    user_def = f"{user_gender}"
                    user_stack.append(user_def)

                if self.context:
                    assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "head"], ""))
                    user_stack.append(Utils.get_nested_value(self.context, ["user", "head"], ""))
                else:
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["profile_picture_context", "assistant", "head"], ""))

            # upper body
            if self.image_type == ImageType.UpperBody or self.image_type == ImageType.FullBody:            
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "upper_body"], ""))

                if self.context:
                    assistant_stack.append(self._clothing(self.context, ["assistant", "upper_body"]))
                    user_stack.append(self._clothing(self.context, ["user", "upper_body"]))
                else:
                    assistant_stack.append(self._clothing(self.profile, ["profile_picture_context", "assistant", "upper_body"]))

            # full body
            if self.image_type == ImageType.FullBody:
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "body"], ""))

                if self.context:
                    assistant_stack.append(self._clothing(self.context, ["assistant", "body"]))
                    user_stack.append(self._clothing(self.context, ["user", "body"]))
                else:
                    assistant_stack.append(self._clothing(self.profile, ["profile_picture_context", "assistant", "body"]))

            if self.context:
                assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "action"], ""))
                user_stack.append(Utils.get_nested_value(self.context, ["user", "action"], ""))
            else:
                assistant_stack.append(Utils.get_nested_value(self.profile, ["profile_picture_context", "assistant", "action"], ""))

            result = ""

            if self.show_assistant:
                assistant_prompt = ", ".join(x for x in assistant_stack if x)
                if self.show_user:
                    assistant_prompt = f"Person A: {assistant_prompt}"
                else:
                    assistant_prompt = f"{assistant_prompt}"
                result += f"{assistant_prompt}\n"

            if self.show_user:
                user_prompt = ", ".join(x for x in user_stack if x)
                if self.show_assistant:
                    user_prompt = f"Person B: {user_prompt}"
                else:
                    user_prompt = f"{user_prompt}"
                result += f"{user_prompt}\n"

            return result
        except Exception as e:
            logger.error(f"failed to build people {repr(e)}")    

    def _build_positive_focus(self) -> str:
        if self.image_type == ImageType.Portrait:
            return prompts.PORTRAIT_FOCUS_PART
        elif self.image_type == ImageType.UpperBody:
            return prompts.UPPER_BODY_FOCUS_PART
        elif self.image_type == ImageType.FullBody:
            return prompts.FULL_BODY_FOCUS_PART
        return ""

    def _image_style(self) -> Dict[str, str]:
        image_style = Utils.get_nested_value(self.profile, ["appearance", "image_style"], "")
        return IMAGE_STYLES.get(image_style, IMAGE_STYLES[DEFAULT_IMAGE_STYLE])

    def _build_positive_general(self) -> str:
        return self._image_style()["positive"]

    def _build_negative_general(self) -> str:
        return self._image_style()["negative"]

    def _build_negative_focus(self) -> str:
        if self.image_type == ImageType.Portrait:
            return prompts.PORTRAIT_NEGATIVE_FOCUS_PART
        elif self.image_type == ImageType.UpperBody:
            return prompts.UPPER_BODY_NEGATIVE_FOCUS_PART
        elif self.image_type == ImageType.FullBody:
            return prompts.FULL_BODY_NEGATIVE_FOCUS_PART
        return ""

    def _build_additional_prompt(self) -> str:
        return f", {self.prompt}" if self.prompt else ""

    def build(self) -> str:
        try:
            positive_prompt = f"""
{self._build_positive_general()}
Location: {self._build_location()}
{self._build_people()},
Parameters: {self._build_positive_focus()}{self._build_additional_prompt()}
            """

            negative_sections = [
                self._build_negative_general(),
                self._build_negative_focus()
            ]
            negative_prompt = ", ".join(negative_sections)

            return positive_prompt, negative_prompt
        except Exception as e:
            logger.error(f"failed to build image prompt {repr(e)}")