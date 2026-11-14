from dataclasses import dataclass
from datetime import datetime

from . import prompts
from app.common import (Utils, CHATTINESS_OPTIONS, DEFAULT_CHATTINESS, QUIET_HOUR_OPTIONS, DEFAULT_QUIET_FROM,
                        DEFAULT_QUIET_UNTIL, PHOTO_OPTIONS, DEFAULT_PHOTOS)

USER_ACTIVE_MINUTES = 30        # the user wrote that recently: they are chatting, don't interrupt


@dataclass(frozen=True)
class Chattiness:
    """the limits of one chattiness level, enforced in code whatever the model answers"""
    max_per_day: int            # messages it writes first per day, 0 = never
    min_hours: float            # between two of them
    max_rows: int               # calendar rows one pass may add: how busy its own day is
    max_pending: int            # one-off rows waiting
    max_sentences: int          # of a message, in the prompt


# "balanced" is how the companion behaved before the settings (#183)
CHATTINESS = {
    "chatty": Chattiness(max_per_day=6, min_hours=1, max_rows=6, max_pending=16, max_sentences=4),
    "talkative": Chattiness(max_per_day=4, min_hours=1.5, max_rows=5, max_pending=14, max_sentences=3),
    "balanced": Chattiness(max_per_day=3, min_hours=2, max_rows=5, max_pending=12, max_sentences=3),
    "reserved": Chattiness(max_per_day=1, min_hours=4, max_rows=3, max_pending=8, max_sentences=2),
    "silent": Chattiness(max_per_day=0, min_hours=24, max_rows=2, max_pending=6, max_sentences=2),
}


class CompanionSettings:
    """a companion's settings (profile.companion_settings, see app.common.companion_settings) and what follows from them:
    its message limits, quiet hours, photos and how busy its day is. a missing or unknown value is the default"""

    def __init__(self, contact: dict):
        settings = Utils.get_nested_value(contact, ["profile", "companion_settings"], {})
        settings = settings if isinstance(settings, dict) else {}
        pick = lambda key, options, default: settings.get(key) if settings.get(key) in options else default
        self.chattiness_name = pick("chattiness", CHATTINESS_OPTIONS, DEFAULT_CHATTINESS)
        self.chattiness = CHATTINESS[self.chattiness_name]
        self.quiet_from = int(pick("quiet_from", QUIET_HOUR_OPTIONS, DEFAULT_QUIET_FROM)[:2])
        self.quiet_until = int(pick("quiet_until", QUIET_HOUR_OPTIONS, DEFAULT_QUIET_UNTIL)[:2])
        self.photos = pick("photos", PHOTO_OPTIONS, DEFAULT_PHOTOS) == "allowed"

    @property
    def excluded_tools(self) -> tuple:
        """the tools a pass is not offered on top of CompanionJob.EXCLUDED_TOOLS"""
        return () if self.photos else ("take_photo",)

    def is_quiet(self, local: datetime) -> bool:
        """local hours [quiet_from, quiet_until), over midnight when quiet_from is later. the same hour twice: never quiet"""
        if self.quiet_from == self.quiet_until:
            return False
        if self.quiet_from < self.quiet_until:
            return self.quiet_from <= local.hour < self.quiet_until
        return local.hour >= self.quiet_from or local.hour < self.quiet_until

    def may_message(self, local: datetime, user_minutes: float | None, sent_today: int, sent_recently: bool) -> tuple[bool, str]:
        """the guardrails of a proactive message: (allowed, reason)"""
        if self.chattiness.max_per_day == 0:
            return False, "silent"
        if self.is_quiet(local):
            return False, "quiet hours"
        if sent_today >= self.chattiness.max_per_day:
            return False, "daily limit reached"
        if sent_recently:
            return False, f"sent one less than {self.chattiness.min_hours:g}h ago"
        if user_minutes is not None and user_minutes < USER_ACTIVE_MINUTES:
            return False, "user is chatting"
        return True, "ok"

    def prompt_values(self) -> dict:
        """the placeholders of the companion's prompts that come from the settings"""
        return {
            "max_per_day": self.chattiness.max_per_day,
            "max_rows": self.chattiness.max_rows,
            "max_sentences": self.chattiness.max_sentences,
            "messaging": prompts.MESSAGING_PARTS[self.chattiness_name],
            "life": prompts.LIFE_PARTS[self.chattiness_name],
        }

    def limits_text(self) -> str:
        """the limits in one line, for the hub management"""
        quiet = "never quiet" if self.quiet_from == self.quiet_until else f"quiet {self.quiet_from}-{self.quiet_until}h"
        return (f"{self.chattiness_name}: {self.chattiness.max_per_day}/day, {self.chattiness.min_hours:g}h apart, {quiet}, "
                f"not within {USER_ACTIVE_MINUTES} min of the user writing, {self.chattiness.max_rows} rows per pass, "
                f"photos {'allowed' if self.photos else 'never'}")
