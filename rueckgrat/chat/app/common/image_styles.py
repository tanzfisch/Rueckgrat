import os

# the image styles of a contact (profile.appearance.image_style), the one list for the chat and the hub: the description
# the chat shows (IMAGE_STYLE_OPTIONS) and the prompt parts the hub's contact images start with (ContactImagePromptCompiler).
# the style goes first in the prompt and stays short: sdxl's text encoder only sees about 75 tokens per chunk and
# compel cuts off long prompts, so style words at the end of the prompt used to be dropped
IMAGE_STYLES = {
    "studio": {
        "description": "controlled lighting, clean backdrop",
        "positive": "studio portrait photo, softbox lighting, seamless backdrop, even light, crisp focus, commercial look",
        "negative": "outdoors, cluttered background, harsh sunlight, candid snapshot, film grain, motion blur, plastic skin, text, mirror, eye artifacts",
    },
    "natural": {
        "description": "ambient light, real-world setting",
        "positive": "candid photo, natural daylight, real-world surroundings, unposed, 35mm film look, natural skin texture",
        "negative": "studio backdrop, softbox lighting, posed, glossy retouched skin, HDR, oversaturated, dramatic lighting, text, mirror, eye artifacts",
    },
    "cinematic": {
        "description": "dramatic movie lighting, moody colors",
        "positive": "cinematic film still, low-key lighting, rim light, anamorphic lens, shallow DOF, teal-orange grade, haze",
        "negative": "flat lighting, plain backdrop, bright even light, snapshot, overexposed, washed out, cartoon, text, mirror, eye artifacts",
    },
    "golden_hour": {
        "description": "warm sunset light, glowing backlight",
        "positive": "golden hour photo, warm low sun, backlit rim light, lens flare, soft haze, outdoor, dreamy warm tones",
        "negative": "midday sun, overcast, cold tones, studio backdrop, flash, harsh shadows, indoor light, text, mirror, eye artifacts",
    },
    "noir": {
        "description": "black and white, hard shadows",
        "positive": "B&W film noir photo, hard key light, deep shadows, venetian blind patterns, high contrast, smoky, 1940s mood",
        "negative": "color, soft even lighting, bright cheerful, flat lighting, modern digital, pastel, text, mirror, eye artifacts",
    },
    "vintage_film": {
        "description": "faded 70s film, grain and light leaks",
        "positive": "1970s analog film photo, faded warm colors, heavy grain, light leaks, soft focus, Kodak Portra look",
        "negative": "digital look, ultra sharp, HDR, crisp modern colors, studio backdrop, clean polished, text, mirror, eye artifacts",
    },
    "editorial": {
        "description": "fashion magazine, bold color, hard flash",
        "positive": "high fashion editorial photo, solid color backdrop, hard flash, strong pose, graphic composition, magazine look",
        "negative": "candid snapshot, cluttered background, natural environment, soft flat lighting, muted colors, film grain, text, mirror, eye artifacts",
    },
    "fantasy": {
        "description": "epic painterly medieval fantasy",
        "positive": "epic high fantasy painting, misty mountains, ancient forests, golden god rays, painterly brushwork, heroic atmosphere",
        "negative": "modern clothing, city, cars, electronics, sci-fi, neon, photograph, studio backdrop, flat lighting, text, mirror, eye artifacts",
    },
    "sci_fi": {
        "description": "futuristic neon, high-tech, cyberpunk",
        "positive": "futuristic sci-fi art, neon city lights, holographic displays, high-tech armor, cyan-magenta lighting, cyberpunk",
        "negative": "medieval, fantasy, rustic, nature only, vintage, sepia, daylight snapshot, plain backdrop, muted colors, text, mirror, eye artifacts",
    },
    "comics": {
        "description": "bold inks, cel shading, flat colors",
        "positive": "comic book illustration, bold black outlines, cel shading, flat vibrant colors, halftone texture, graphic novel style",
        "negative": "photograph, photorealistic, soft gradients, blurry lines, 3D render, muted colors, film grain, text, eye artifacts",
    },
    "anime": {
        "description": "anime illustration, clean lines, cel shading",
        "positive": "anime illustration, clean lineart, cel shading, vibrant colors, expressive eyes, detailed anime background",
        "negative": "photograph, photorealistic, 3D render, western comic, rough sketch, nsfw, nudity, sexual, child, loli, chibi, deformed anatomy, text, eye artifacts",
    },
    "origami": {
        "description": "folded paper figure, crisp creases",
        "positive": "origami paper craft figure, folded paper, crisp creases, paper texture, soft studio light, papercraft diorama",
        "negative": "photograph of a real person, skin texture, painting, cartoon, 3D render, plastic, glossy, text, eye artifacts",
    },
    "charcoal_sketch": {
        "description": "monochrome hand-drawn charcoal",
        "positive": "charcoal sketch portrait, expressive strokes, grainy shading, monochrome, textured paper, fine art drawing",
        "negative": "color, photograph, photorealistic, digital art, clean lineart, cel shading, 3D render, glossy, text, eye artifacts",
    },
    "watercolor": {
        "description": "soft washes, bleeding pigments",
        "positive": "watercolor painting portrait, soft washes, bleeding pigments, visible paper grain, loose brushwork, light airy palette",
        "negative": "photograph, photorealistic, hard outlines, cel shading, 3D render, digital art, oversaturated, glossy, text, eye artifacts",
    },
    "classic_oil_portrait": {
        "description": "classic old master oil painting",
        "positive": "classic oil painting portrait, old master style, rich chiaroscuro, visible brushstrokes, canvas texture, dark warm background",
        "negative": "photograph, photorealistic, modern clothing, cartoon, anime, flat colors, 3D render, neon, text, eye artifacts",
    },
}

DEFAULT_IMAGE_STYLE = "studio"
IMAGE_STYLE_OPTIONS = {style: values["description"] for style, values in IMAGE_STYLES.items()}

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"
IMAGE_STYLE_ICONS = {style: f"{ASSETS_DIR}/icons/{style}.png" for style in IMAGE_STYLE_OPTIONS}
