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
        "positive": "studio portrait photo, softbox lighting, seamless backdrop, even light, crisp focus, commercial look",
        "negative": "outdoors, cluttered background, harsh sunlight, candid snapshot, film grain, motion blur, plastic skin, text, mirror, eye artifacts",
    },
    "natural": {
        "positive": "candid photo, natural daylight, real-world surroundings, unposed, 35mm film look, natural skin texture",
        "negative": "studio backdrop, softbox lighting, posed, glossy retouched skin, HDR, oversaturated, dramatic lighting, text, mirror, eye artifacts",
    },
    "cinematic": {
        "positive": "cinematic film still, low-key lighting, rim light, anamorphic lens, shallow DOF, teal-orange grade, haze",
        "negative": "flat lighting, plain backdrop, bright even light, snapshot, overexposed, washed out, cartoon, text, mirror, eye artifacts",
    },
    "golden_hour": {
        "positive": "golden hour photo, warm low sun, backlit rim light, lens flare, soft haze, outdoor, dreamy warm tones",
        "negative": "midday sun, overcast, cold tones, studio backdrop, flash, harsh shadows, indoor light, text, mirror, eye artifacts",
    },
    "noir": {
        "positive": "B&W film noir photo, hard key light, deep shadows, venetian blind patterns, high contrast, smoky, 1940s mood",
        "negative": "color, soft even lighting, bright cheerful, flat lighting, modern digital, pastel, text, mirror, eye artifacts",
    },
    "vintage_film": {
        "positive": "1970s analog film photo, faded warm colors, heavy grain, light leaks, soft focus, Kodak Portra look",
        "negative": "digital look, ultra sharp, HDR, crisp modern colors, studio backdrop, clean polished, text, mirror, eye artifacts",
    },
    "editorial": {
        "positive": "high fashion editorial photo, solid color backdrop, hard flash, strong pose, graphic composition, magazine look",
        "negative": "candid snapshot, cluttered background, natural environment, soft flat lighting, muted colors, film grain, text, mirror, eye artifacts",
    },
    "fantasy": {
        "positive": "epic high fantasy painting, misty mountains, ancient forests, golden god rays, painterly brushwork, heroic atmosphere",
        "negative": "modern clothing, city, cars, electronics, sci-fi, neon, photograph, studio backdrop, flat lighting, text, mirror, eye artifacts",
    },
    "sci_fi": {
        "positive": "futuristic sci-fi art, neon city lights, holographic displays, high-tech armor, cyan-magenta lighting, cyberpunk",
        "negative": "medieval, fantasy, rustic, nature only, vintage, sepia, daylight snapshot, plain backdrop, muted colors, text, mirror, eye artifacts",
    },
    "comics": {
        "positive": "comic book illustration, bold black outlines, cel shading, flat vibrant colors, halftone texture, graphic novel style",
        "negative": "photograph, photorealistic, soft gradients, blurry lines, 3D render, muted colors, film grain, text, eye artifacts",
    },
    "anime": {
        "positive": "anime illustration, clean lineart, cel shading, vibrant colors, expressive eyes, detailed anime background",
        "negative": "photograph, photorealistic, 3D render, western comic, rough sketch, nsfw, nudity, sexual, child, loli, chibi, deformed anatomy, text, eye artifacts",
    },
    "origami": {
        "positive": "origami paper craft figure, folded paper, crisp creases, paper texture, soft studio light, papercraft diorama",
        "negative": "photograph of a real person, skin texture, painting, cartoon, 3D render, plastic, glossy, text, eye artifacts",
    },
    "charcoal_sketch": {
        "positive": "charcoal sketch portrait, expressive strokes, grainy shading, monochrome, textured paper, fine art drawing",
        "negative": "color, photograph, photorealistic, digital art, clean lineart, cel shading, 3D render, glossy, text, eye artifacts",
    },
    "watercolor": {
        "positive": "watercolor painting portrait, soft washes, bleeding pigments, visible paper grain, loose brushwork, light airy palette",
        "negative": "photograph, photorealistic, hard outlines, cel shading, 3D render, digital art, oversaturated, glossy, text, eye artifacts",
    },
    "classic_oil_portrait": {
        "positive": "classic oil painting portrait, old master style, rich chiaroscuro, visible brushstrokes, canvas texture, dark warm background",
        "negative": "photograph, photorealistic, modern clothing, cartoon, anime, flat colors, 3D render, neon, text, eye artifacts",
    },
}

DEFAULT_IMAGE_STYLE = IMAGE_STYLES["studio"]

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
                # skip everything that could be derived from a reference image
                if self.use_facial_features:
                    assistant_stack.append(Utils.get_nested_value(self.contact, ["identity", "gender"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "general"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "hair"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "face"], ""))
                    assistant_stack.append(Utils.get_nested_value(self.profile, ["appearance", "skin"], ""))

                # only needed when the user is in the picture. a new user has no user data yet
                if self.show_user and self.user_data:
                    user_profile = json.loads(self.user_data["profile"])
                    user_gender = Utils.get_nested_value(user_profile, ["gender"], "")
                    user_age = self.age_to_text(int(Utils.get_nested_value(user_profile, ["age"], "")))
                    user_hair_color = Utils.get_nested_value(user_profile, ["hair_color"], "")
                    user_eye_color = Utils.get_nested_value(user_profile, ["eye_color"], "")
                    user_ethnicity = Utils.get_nested_value(user_profile, ["ethnicity"], "")
                    user_body_type = Utils.get_nested_value(user_profile, ["body_type"], "")
                    user_def = f"{user_gender}, {user_age}, {user_body_type}, {user_ethnicity}, {user_hair_color} hair, {user_eye_color} eyes, "
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
            return "tight face crop, face fills frame, centered, detailed eyes"
        elif self.image_type == ImageType.UpperBody:
            return "waist-up, mid-torso to head, face and upper body fully visible, centered, chest and shoulders prominent, detailed eyes"
        elif self.image_type == ImageType.FullBody:
            return "full body, head to toe, entire figure in frame, head not cropped, centered, camera pulled back"
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
            return "full body, long shot, medium shot, upper body, small subject, cropped head, extreme close-up, blurry or distorted face, off-center, artifacts in eyes"
        elif self.image_type == ImageType.UpperBody:
            return "full body, long shot, head to toe, feet visible, cropped head, extreme close-up, face only, off-center, subject too small, lower body dominant, artifacts in eyes"
        elif self.image_type == ImageType.FullBody:
            return "cropped head, partial body, upper body only, medium shot, close-up, legs or feet cut off, subject out of frame, off-center, camera too close"
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