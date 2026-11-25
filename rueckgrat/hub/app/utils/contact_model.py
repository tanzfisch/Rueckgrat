"""
A contact's json as the hub stores it: identity (the contacts table's columns) and profile (its json column).
everything that reaches the db goes through Contact (PATCH /contacts/{id}, the default character, the contact
generator), so only the fields the chat and the hub read are kept, unknown keys are dropped. that also drops the
companion switch of an exported character file (profile.companion_settings.companion): only
PUT /contacts/{id}/companion sets the companion (profile.companion, kept by ChatDB.update_contact).
a save sends the whole contact: the profile replaces the stored one, identity fields left out keep theirs
"""
from typing import Annotated, Iterable, List, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.common import IMAGE_STYLE_OPTIONS, CHATTINESS_OPTIONS, QUIET_HOUR_OPTIONS, PHOTO_OPTIONS, REACH_WINDOW_OPTIONS

GENDERS = ("male", "female")     # the contacts table's CHECK


def option(options: Iterable[str]):
    """one of the options, "" (a select the chat's profile page left empty) is unset"""
    return Annotated[Optional[Literal[tuple(options)]], BeforeValidator(lambda value: value or None)]


class Part(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Identity(Part):
    name: str
    gender: option(GENDERS) = None
    role: Optional[str] = None
    personality: Optional[str] = None


class Appearance(Part):
    image_style: option(IMAGE_STYLE_OPTIONS) = None
    general: Optional[str] = None
    face: Optional[str] = None
    hair: Optional[str] = None
    skin: Optional[str] = None
    upper_body: Optional[str] = None
    body: Optional[str] = None


class Objectives(Part):
    primary: Optional[str] = None
    secondary: Optional[List[str]] = None


class InteractionStyle(Part):
    tone: Optional[str] = None
    engagement: Optional[str] = None
    quirks: Optional[List[str]] = None


class PictureAssistant(Part):
    """what the contact wears and does in its profile picture"""
    action: Optional[str] = None
    head: Optional[str] = None
    upper_body: Optional[str] = None
    body: Optional[str] = None


class PictureContext(Part):
    location: Optional[str] = None
    topic: Optional[str] = None
    assistant: Optional[PictureAssistant] = None


class LlmParameters(Part):
    temperature: Optional[float] = None
    preffered_context_size: Optional[int] = None


class ImageParameters(Part):
    seed: Optional[int] = None
    steps: Optional[int] = None
    cfg: Optional[float] = None
    model: Optional[str] = None


class TtsParameters(Part):
    voice_id: Optional[str] = None


class CompanionSettings(Part):
    """app.companion.settings.CompanionSettings reads them, unset is the default"""
    chattiness: option(CHATTINESS_OPTIONS) = None
    quiet_from: option(QUIET_HOUR_OPTIONS) = None
    quiet_until: option(QUIET_HOUR_OPTIONS) = None
    photos: option(PHOTO_OPTIONS) = None
    reach_window: option(REACH_WINDOW_OPTIONS) = None


class Profile(Part):
    background_hook: Optional[str] = None
    relationship: Optional[str] = None
    body_language: Optional[str] = None
    style: Optional[str] = None
    sfw: Optional[str] = None
    appearance: Optional[Appearance] = None
    objectives: Optional[Objectives] = None
    interaction_style: Optional[InteractionStyle] = None
    profile_picture_context: Optional[PictureContext] = None
    llm_parameters: Optional[LlmParameters] = None
    image_parameters: Optional[ImageParameters] = None
    tts_parameters: Optional[TtsParameters] = None
    companion_settings: Optional[CompanionSettings] = None


class Contact(Part):
    identity: Identity
    profile: Profile

    def columns(self) -> dict:
        """the identity fields given, as the contacts table's columns"""
        return self.identity.model_dump(exclude_none=True)

    def profile_json(self) -> dict:
        """the profile as stored, unset fields left out"""
        return self.profile.model_dump(exclude_none=True)

    def resolve_voice(self, resolve) -> None:
        """the voice_id through resolve (a voices.json id or hash to the user's uuid), when there is one"""
        tts = self.profile.tts_parameters
        if tts is not None and tts.voice_id is not None:
            tts.voice_id = resolve(tts.voice_id)
