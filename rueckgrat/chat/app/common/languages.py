# the languages of the translator, by ISO 639-1 code (whisper takes it as the stt language).
# tts: chatterbox multilingual can speak it (MULTILINGUAL_LANGUAGES in node/app/utils/tts.py)
LANGUAGES = {
    "de": {"name": "German", "flag": "🇩🇪", "tts": True},
    "en": {"name": "English", "flag": "🇬🇧", "tts": True},
    "vi": {"name": "Vietnamese", "flag": "🇻🇳", "tts": False},
    "fr": {"name": "French", "flag": "🇫🇷", "tts": True},
    "es": {"name": "Spanish", "flag": "🇪🇸", "tts": True},
    "it": {"name": "Italian", "flag": "🇮🇹", "tts": True},
    "pt": {"name": "Portuguese", "flag": "🇵🇹", "tts": True},
    "pl": {"name": "Polish", "flag": "🇵🇱", "tts": True},
    "tr": {"name": "Turkish", "flag": "🇹🇷", "tts": True},
    "ru": {"name": "Russian", "flag": "🇷🇺", "tts": True},
    "zh": {"name": "Chinese", "flag": "🇨🇳", "tts": True},
    "ja": {"name": "Japanese", "flag": "🇯🇵", "tts": True},
    "ko": {"name": "Korean", "flag": "🇰🇷", "tts": True},
    "th": {"name": "Thai", "flag": "🇹🇭", "tts": False},
    "ar": {"name": "Arabic", "flag": "🇸🇦", "tts": True},
    "hi": {"name": "Hindi", "flag": "🇮🇳", "tts": True},
}


def language_name(code: str) -> str:
    return LANGUAGES.get(code, {}).get("name", code)
