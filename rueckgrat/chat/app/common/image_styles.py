import re
import os

IMAGE_STYLE_OPTIONS = {
    "studio": "controlled lighting, clean backdrop",
    "natural": "ambient light, real-world setting",
    "cinematic": "dramatic movie lighting, moody colors",
    "golden_hour": "warm sunset light, glowing backlight",
    "noir": "black and white, hard shadows",
    "vintage_film": "faded 70s film, grain and light leaks",
    "editorial": "fashion magazine, bold color, hard flash",
    "fantasy": "epic painterly medieval fantasy",
    "sci_fi": "futuristic neon, high-tech, cyberpunk",
    "comics": "bold inks, cel shading, flat colors",
    "anime": "anime illustration, clean lines, cel shading",
    "origami": "folded paper figure, crisp creases",
    "charcoal_sketch": "monochrome hand-drawn charcoal",
    "watercolor": "soft washes, bleeding pigments",
    "classic_oil_portrait": "classic old master oil painting",
}

DEFAULT_IMAGE_STYLE = "studio"

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"
IMAGE_STYLE_ICONS = {style: f"{ASSETS_DIR}/icons/{style}.png" for style in IMAGE_STYLE_OPTIONS}
