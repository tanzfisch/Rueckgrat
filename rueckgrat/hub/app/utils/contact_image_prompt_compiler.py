import json
from typing import Dict, Any
from enum import Enum

from app.common import get_logger, Utils
logger = get_logger()

class ImageType(Enum):
    Portrait = 1
    UpperBody = 2
    FullBody = 3

# image styles selectable per contact (profile.appearance.image_style), keep in sync with SELECT_OPTIONS in chat/app/ui/profile_page.py.
# the style goes first in the prompt and stays short: sdxl's text encoder only sees about 75 tokens per chunk and
# compel cuts off long prompts, so style words at the end of the prompt used to be dropped
IMAGE_STYLES = {
    "studio": {
        "positive": "studio portrait photograph, professional softbox lighting, seamless plain backdrop, clean even light, crisp focus, polished commercial look",
        "negative": "outdoors, real-world environment, cluttered background, harsh sunlight, candid snapshot, film grain, motion blur, plastic skin, airbrushed, text, mirror, artifacts in eyes",
    },
    "natural": {
        "positive": "candid photograph, available natural daylight, real-world surroundings, environmental background, unposed, 35mm film look, natural skin texture",
        "negative": "studio backdrop, softbox lighting, seamless background, posed, glossy retouched skin, HDR, oversaturated, dramatic lighting, digital art, text, mirror, artifacts in eyes",
    },
    "cinematic": {
        "positive": "cinematic film still, dramatic low-key lighting, strong rim light, anamorphic lens, shallow depth of field, moody teal and orange color grade, atmospheric haze",
        "negative": "flat lighting, plain backdrop, bright even light, snapshot, overexposed, washed out colors, cartoon, 3D render, text, mirror, artifacts in eyes",
    },
    "golden_hour": {
        "positive": "golden hour photograph, warm low sun, backlit glowing rim light, lens flare, soft warm haze, outdoor setting, gentle highlights, dreamy warm tones",
        "negative": "midday sun, overcast, cold blue tones, studio backdrop, flash photography, harsh shadows, indoor lighting, desaturated, text, mirror, artifacts in eyes",
    },
    "noir": {
        "positive": "black and white film noir photograph, hard single key light, deep shadows, venetian blind shadow pattern, high contrast monochrome, smoky atmosphere, 1940s mood",
        "negative": "color, colorful, saturated, soft even lighting, bright cheerful, flat lighting, modern digital look, pastel, text, mirror, artifacts in eyes",
    },
    "vintage_film": {
        "positive": "1970s analog film photograph, faded warm colors, heavy film grain, light leaks, soft focus, slightly washed out, Kodak Portra look, retro snapshot",
        "negative": "digital look, ultra sharp, HDR, crisp modern colors, studio backdrop, clean polished, high contrast, oversaturated, text, mirror, artifacts in eyes",
    },
    "editorial": {
        "positive": "high fashion editorial photograph, bold solid color backdrop, hard directional flash, strong confident pose, graphic composition, vivid styling, magazine cover look",
        "negative": "candid snapshot, cluttered background, natural environment, soft flat lighting, muted colors, amateur photo, film grain, text, mirror, artifacts in eyes",
    },
    "fantasy": {
        "positive": "epic high fantasy painting, medieval fantasy world, sweeping misty mountains and ancient forests, golden god rays through clouds, painterly brushwork, rich earthy tones, heroic atmosphere",
        "negative": "modern clothing, modern city, cars, electronics, sci-fi, neon, photograph, snapshot, studio backdrop, flat lighting, cartoon, anime, text, mirror, artifacts in eyes",
    },
    "sci_fi": {
        "positive": "futuristic sci-fi concept art, neon city lights, glowing holographic displays, sleek high-tech armor and gadgets, cyan and magenta lighting, rain-slick reflections, cyberpunk atmosphere",
        "negative": "medieval, fantasy, rustic, nature only, vintage, sepia, daylight snapshot, plain studio backdrop, muted colors, painterly, cartoon, text, mirror, artifacts in eyes",
    },
    "comics": {
        "positive": "comic book illustration, bold black ink outlines, cel shading, flat vibrant colors, halftone dot texture, dynamic panel composition, graphic novel style",
        "negative": "photograph, photorealistic, realistic skin texture, soft gradients, blurry lines, 3D render, muted colors, film grain, speech bubbles, text, artifacts in eyes",
    },
    "hentai": {
        "positive": "anime illustration, adult character, mature proportions, clean lineart, cel shading, soft pastel color palette, large expressive eyes, glossy hair highlights, detailed anime background",
        "negative": "photograph, photorealistic, 3D render, western comic style, rough sketch, child, childlike, underage, loli, chibi, deformed anatomy, text, watermark, artifacts in eyes",
    },
}
DEFAULT_IMAGE_STYLE = {
    "positive": "high quality, high detail, correct anatomy",
    "negative": "low quality, wrong anatomy, text, mirror, artifacts in eyes",
}

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

    def _image_style(self) -> Dict[str, str]:
        image_style = Utils.get_nested_value(self.profile, ["appearance", "image_style"], "")
        return IMAGE_STYLES.get(image_style, DEFAULT_IMAGE_STYLE)

    def _build_positive_general(self) -> str:
        return self._image_style()["positive"]

    def _build_negative_general(self) -> str:
        return self._image_style()["negative"]

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