import re
from typing import Dict, Any
from enum import Enum

from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class ImageType(Enum):
    Portrait = 1
    UpperBody = 2
    FullBody = 3

class ImagePromptCompiler:
    def __init__(self, contact: Dict[str, Any], context: Dict[str, Any] = None, image_type: ImageType = ImageType.FullBody, user_present: bool = False, prompt: str = None):
        self.contact = contact
        self.profile = contact.get("profile", {})
        self.appearance = self.profile.get("appearance", {})
        self.image_type = image_type
        self.user_present = user_present
        self.prompt = prompt
        self.context = context

        if not self.context:
            logger.warning("got no context yet")

    def _build_location(self) -> str:
        try:
            if self.context:
                return Utils.get_nested_value(self.context, ["location"], "")
            else:
                return Utils.get_nested_value(self.profile, ["start_context", "location"], "")
        except Exception as e:
            logger.error(f"failed to build location {repr(e)}")

    def _build_topic(self) -> str:
        try:
            if self.context:
                return Utils.get_nested_value(self.context, ["topic"], "")
            else:
                return Utils.get_nested_value(self.profile, ["start_context", "topic"], "")
        except Exception as e:
            logger.error(f"failed to build topic {repr(e)}")

    def _build_people(self) -> str:
        try:
            gender = Utils.get_nested_value(self.contact, ["gender"], "")            
            general = Utils.get_nested_value(self.appearance, ["general"], "")
            face = Utils.get_nested_value(self.appearance, ["face"], "")
            hair = Utils.get_nested_value(self.appearance, ["hair"], "")
            skin = Utils.get_nested_value(self.appearance, ["skin"], "")

            upper_body = Utils.get_nested_value(self.appearance, ["upper_body"], "")
            body = Utils.get_nested_value(self.appearance, ["body"], "")

            assistant_stack = []
            user_stack = []

            # portrait
            if self.image_type == ImageType.Portrait or self.image_type == ImageType.UpperBody or self.image_type == ImageType.FullBody:            
                assistant_stack.append(gender)
                assistant_stack.append(general)
                assistant_stack.append(hair)
                assistant_stack.append(face)
                assistant_stack.append(skin)

                user_stack.append("male, caucasian, athletic, short blonde hair") # TODO need user settings

                if self.context:
                    assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "head"], ""))
                    user_stack.append(Utils.get_nested_value(self.context, ["user", "head"], ""))
                else:
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["start_context", "assistant", "head"], ""))
                    user_stack.append(Utils.get_nested_value(self.profile, ["start_context", "user", "head"], ""))

            # upper body
            if self.image_type == ImageType.UpperBody or self.image_type == ImageType.FullBody:            
                assistant_stack.append(upper_body)

                if self.context:
                    assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "upper_body"], ""))
                    user_stack.append(Utils.get_nested_value(self.context, ["user", "upper_body"], ""))
                else:
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["start_context", "assistant", "upper_body"], ""))
                    user_stack.append(Utils.get_nested_value(self.profile, ["start_context", "user", "upper_body"], ""))

            # full body
            if self.image_type == ImageType.FullBody:
                assistant_stack.append(body)

                if self.context:
                    assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "body"], ""))
                    user_stack.append(Utils.get_nested_value(self.context, ["user", "body"], ""))
                else:
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["start_context", "assistant", "body"], ""))
                    user_stack.append(Utils.get_nested_value(self.profile, ["start_context", "user", "body"], ""))

            if self.context:
                assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "action"], ""))
                user_stack.append(Utils.get_nested_value(self.context, ["user", "action"], ""))
            else:
                assistant_stack.append(Utils.get_nested_value(self.profile, ["start_context", "assistant", "action"], ""))
                user_stack.append(Utils.get_nested_value(self.profile, ["start_context", "user", "action"], ""))

            assistant = ", ".join(x for x in assistant_stack if x)
            assistant = f"Person A: {assistant}"

            result = f"{assistant}\n"

            if self.user_present:
                user = ", ".join(x for x in user_stack if x)
                if user:
                    user = f"Person B: {user}"
                    result += f"{user}\n"   

            return result
        except Exception as e:
            logger.error(f"failed to build people {repr(e)}")    

    def _build_positive_focus(self) -> str:
        if self.image_type == ImageType.Portrait:
            return "tight facial crop, face centered, full frame occupied by face, no body parts below the chin or above the forehead cut off unnaturally"
        elif self.image_type == ImageType.UpperBody:
            return "medium shot, waist-up portrait, subject framed from mid-torso to top of head, face and upper body fully visible, centered composition, balanced framing, chest and shoulders prominent, no full body, no cropped head, camera at chest level, portrait orientation"
        elif self.image_type == ImageType.FullBody:
            return "full body shot, head-to-toe visible, entire figure in frame, subject fully visible from top of head to feet, head clearly visible and not cropped, centered composition, balanced framing, full height portrait, camera pulled back, portrait orientation"
        
        return ""

    def _build_positive_general(self) -> str:
        image_style = self.appearance["image_style"]
        if image_style == "natural":
            return "natural photograph, realistic lighting, soft natural light, subtle shadows, true-to-life colors, high quality, high detail, sharp focus, symmetrical anatomy, natural skin texture, visible pores, slight imperfections, candid feel, unposed, real-world camera look, depth of field, realistic lens perspective, no overprocessing, no HDR look, film-like color grading"
        elif image_style == "studio":
            return "realistic photograph, natural or soft diffused lighting, true-to-life colors, realistic skin texture with minor imperfections, subtle shadows, natural depth of field, sharp but not hyper-detailed focus, candidly framed, slight grain or film texture, neutral color grading, authentic textures and reflections, balanced composition without over-polishing, high-quality yet natural look"
        else:
            return "high quality, high detail, symmetrical anatomy"
        
    def _build_negative_general(self) -> str:
        image_style = self.appearance["image_style"]
        if image_style == "natural":        
            return "stylized image, artificial lighting, dramatic lighting, high contrast, vivid colors, oversaturated tones, glossy skin, smooth texture, flawless complexion, hyper-detailed, ultra sharp, HDR effect, cinematic look, perfect symmetry, exaggerated features, studio lighting, digital art style, 3D render look, polished, unreal perfection"
        elif image_style == "studio":
            return "over-processed, plastic, overly smooth skin, exaggerated highlights, hyper-realistic textures, studio lighting effects, artificial glow, airbrushed, unnatural colors, over-sharpened, commercial retouching, excessive contrast or saturation, heavy filters"
        else:
            return "high quality, high detail, symmetrical anatomy"
    
    def _build_negative_focus(self) -> str:        
        if self.image_type == ImageType.Portrait:
            return "full body, long shot, wide shot, medium shot, upper body only, torso dominant, subject too far away, small subject, zoomed out, cropped head, cut off top of head, out of frame face, partial face, face out of frame, extreme close-up, face too zoomed in, blurry face, distorted face, off-center composition, tilted framing"
        elif self.image_type == ImageType.UpperBody:
            return "full body, long shot, wide shot, extreme wide shot, head to toe, feet visible, cropped head, cut off head, out of frame head, extreme close-up, close-up face only, zoomed in face, partial face, off-center framing, tilted composition, subject too small, subject too far away, body out of frame, lower body dominant"
        elif self.image_type == ImageType.FullBody:
            return "cropped head, cut off head, out of frame head, missing head, partial body, upper body only, medium shot, close-up, extreme close-up, zoomed in, torso only, legs cut off, feet cut off, subject out of frame, poorly framed, off-center, tilted composition, subject too close, camera too close"
        
        return ""

    def _build_additional_prompt(self) -> str:
        return self.prompt if self.prompt else ""

    def build(self) -> str:
        try:
            positive_prompt = f"""
{self._build_people()},
Location: {self._build_location()}
Topic: {self._build_topic()}
Parameters: {self._build_positive_focus()}, {self._build_positive_general()}, {self._build_additional_prompt()}
            """

            negative_sections = [
                self._build_negative_general(),
                self._build_negative_focus()
            ]
            negative_prompt = ", ".join(negative_sections)

            logger.debug(f"positive image prompt generated: {positive_prompt}")
            logger.debug(f"negative image prompt generated: {negative_prompt}")

            return positive_prompt, negative_prompt
        except Exception as e:
            logger.error(f"failed to build image prompt {repr(e)}")