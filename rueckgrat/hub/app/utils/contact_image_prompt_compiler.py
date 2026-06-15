import json
from typing import Dict, Any
from enum import Enum

from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class ImageType(Enum):
    Portrait = 1
    UpperBody = 2
    FullBody = 3

class ContactImagePromptCompiler:
    def __init__(self, contact: Dict[str, Any], user_data: Dict[str, Any], context: Dict[str, Any] = None, image_type: ImageType = ImageType.FullBody, show_assistant: bool = True, show_user: bool = False, prompt: str = None):
        self.contact = contact
        self.user_data = user_data
        self.profile = contact.get("profile", {})
        self.image_type = image_type
        self.show_assistant = show_assistant
        self.show_user = show_user        
        self.prompt = prompt
        self.context = context        

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

    def age_to_text(self, age: int):
        if age < 18: return ""
        elif age < 22: return "young"
        elif age < 27: return "young adult"
        elif age < 45: return "mature"
        elif age < 60: return "middle-aged"
        else: return "senior"

    def _build_people(self) -> str:
        try:
            assistant_stack = []
            user_stack = []

            # portrait
            if self.image_type == ImageType.Portrait or self.image_type == ImageType.UpperBody or self.image_type == ImageType.FullBody:            
                assistant_stack.append(Utils.get_nested_value(self.contact, ["identity", "gender"], ""))
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "general"], ""))
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "hair"], ""))
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "face"], ""))
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "skin"], ""))

                user_profile = json.loads(self.user_data["profile"])
                user_gender = Utils.get_nested_value(user_profile, ["gender"], "")
                user_age = self.age_to_text(int(Utils.get_nested_value(user_profile, ["age"], "")))
                user_hair_color = Utils.get_nested_value(user_profile, ["hair_color"], "")
                user_eye_color = Utils.get_nested_value(user_profile, ["eye_color"], "")
                user_ethnicity = Utils.get_nested_value(user_profile, ["ethnicity"], "")
                user_body_type = Utils.get_nested_value(user_profile, ["body_type"], "")
                user_def = f"{user_gender}, {user_age} year old, {user_body_type}, {user_ethnicity}, {user_hair_color} hair, {user_eye_color} eyes, "
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
                    assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "upper_body"], ""))
                    user_stack.append(Utils.get_nested_value(self.context, ["user", "upper_body"], ""))
                else:
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["profile_picture_context", "assistant", "upper_body"], ""))

            # full body
            if self.image_type == ImageType.FullBody:
                assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "body"], ""))

                if self.context:
                    assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "body"], ""))
                    user_stack.append(Utils.get_nested_value(self.context, ["user", "body"], ""))
                else:
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["profile_picture_context", "assistant", "body"], ""))

            if self.context:
                assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "action"], ""))
                user_stack.append(Utils.get_nested_value(self.context, ["user", "action"], ""))
            else:
                assistant_stack.append(Utils.get_nested_value(self.profile, ["profile_picture_context", "assistant", "action"], ""))

            result = ""

            if self.show_assistant:
                assistant_prompt = ", ".join(x for x in assistant_stack if x)
                assistant_prompt = f"Person A: {assistant_prompt}"
                result += f"{assistant_prompt}\n"

            if self.show_user:
                user_prompt = ", ".join(x for x in user_stack if x)
                user_prompt = f"Person B: {user_prompt}"
                result += f"{user_prompt}\n"

            return result
        except Exception as e:
            logger.error(f"failed to build people {repr(e)}")    

    def _build_positive_focus(self) -> str:
        if self.image_type == ImageType.Portrait:
            return "tight facial crop, face centered, full frame occupied by face, no body parts below the chin or above the forehead cut off unnaturally, detailed eyes"
        elif self.image_type == ImageType.UpperBody:
            return "medium shot, waist-up portrait, subject framed from mid-torso to top of head, face and upper body fully visible, centered composition, balanced framing, chest and shoulders prominent, no full body, no cropped head, camera at chest level, portrait orientation, detailed eyes"
        elif self.image_type == ImageType.FullBody:
            return "full body shot, head-to-toe visible, entire figure in frame, subject fully visible from top of head to feet, head clearly visible and not cropped, centered composition, balanced framing, full height portrait, camera pulled back, portrait orientation"
        
        return ""

    def _build_positive_general(self) -> str:
        image_style = Utils.get_nested_value(self.profile, ["appearance", "image_style"], "")
        if image_style == "natural":
            return "natural photograph, realistic lighting, soft natural light, subtle shadows, true-to-life colors, high quality, high detail, sharp focus, correct anatomy, natural skin texture, visible pores, slight imperfections, candid feel, unposed, real-world camera look, depth of field, realistic lens perspective, no overprocessing, no HDR look, film-like color grading"
        elif image_style == "studio":
            return "realistic photograph, studio lighting effects, natural or soft diffused lighting, true-to-life colors, realistic skin texture with minor imperfections, correct anatomy, subtle shadows, natural depth of field, sharp but not hyper-detailed focus, candidly framed, slight grain or film texture, neutral color grading, authentic textures and reflections, balanced composition without over-polishing, high-quality yet natural look"
        else:
            return "high quality, high detail, correct anatomy"
        
    def _build_negative_general(self) -> str:
        image_style = Utils.get_nested_value(self.profile, ["appearance", "image_style"], "")
        if image_style == "natural":        
            return "stylized image, artificial lighting, dramatic lighting, high contrast, vivid colors, oversaturated tones, glossy skin, smooth texture, flawless complexion, hyper-detailed, ultra sharp, HDR effect, cinematic look, perfect symmetry, exaggerated features, studio lighting, digital art style, 3D render look, polished, unreal perfection, text, mirror, artifacts in eyes"
        elif image_style == "studio":
            return "over-processed, plastic, overly smooth skin, exaggerated highlights, hyper-realistic textures, artificial glow, airbrushed, unnatural colors, over-sharpened, commercial retouching, excessive contrast or saturation, heavy filters, text, mirror, artifacts in eyes"
        else:
            return "high quality, high detail, wrong anatomy, text, mirror, artifacts in eyes"
    
    def _build_negative_focus(self) -> str:        
        if self.image_type == ImageType.Portrait:
            return "full body, long shot, wide shot, medium shot, upper body only, torso dominant, subject too far away, small subject, zoomed out, cropped head, cut off top of head, out of frame face, partial face, face out of frame, extreme close-up, face too zoomed in, blurry face, distorted face, off-center composition, tilted framing, artifacts in eyes"
        elif self.image_type == ImageType.UpperBody:
            return "full body, long shot, wide shot, extreme wide shot, head to toe, feet visible, cropped head, cut off head, out of frame head, extreme close-up, close-up face only, zoomed in face, partial face, off-center framing, tilted composition, subject too small, subject too far away, body out of frame, lower body dominant, artifacts in eyes"
        elif self.image_type == ImageType.FullBody:
            return "cropped head, cut off head, out of frame head, missing head, partial body, upper body only, medium shot, close-up, extreme close-up, zoomed in, torso only, legs cut off, feet cut off, subject out of frame, poorly framed, off-center, tilted composition, subject too close, camera too close"
        
        return ""

    def _build_additional_prompt(self) -> str:
        return f", {self.prompt}" if self.prompt else ""

    def build(self) -> str:
        try:
            positive_prompt = f"""
Location: {self._build_location()}
{self._build_people()},
Parameters: {self._build_positive_focus()}, {self._build_positive_general()}{self._build_additional_prompt()}
            """

            negative_sections = [
                self._build_negative_general(),
                self._build_negative_focus()
            ]
            negative_prompt = ", ".join(negative_sections)

            return positive_prompt, negative_prompt
        except Exception as e:
            logger.error(f"failed to build image prompt {repr(e)}")