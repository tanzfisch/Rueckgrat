"""the companion settings of a contact (profile.companion_settings), shared by the chat's profile page and the hub
(app.companion.settings.CompanionSettings derives the companion's limits from them). a missing or unknown value is the default"""

# how often it writes first, also how busy its own day is and how long its messages are
CHATTINESS_OPTIONS = {
    "chatty": "writes often, shares small moments, a busy life",
    "talkative": "writes when something is on its mind",
    "balanced": "writes now and then, only with a reason",
    "reserved": "rarely writes first, a quiet life",
    "silent": "never writes first, lives its own day",
}
DEFAULT_CHATTINESS = "balanced"

# local hours [from, until) without messages it writes first, the same hour twice means no quiet hours
QUIET_HOUR_OPTIONS = {f"{hour:02d}:00": "" for hour in range(24)}
DEFAULT_QUIET_FROM = "22:00"
DEFAULT_QUIET_UNTIL = "08:00"

PHOTO_OPTIONS = {
    "allowed": "may take a photo and send it with a message",
    "never": "never sends photos",
}
DEFAULT_PHOTOS = "allowed"

# how long a prepared reach-out waits for the user to open the contact (surprise) before it is sent (reach_out)
REACH_WINDOW_OPTIONS = {
    "15m": "15 minutes, more likely to catch you walking in",
    "30m": "30 minutes",
    "1h": "1 hour",
    "2h": "2 hours",
    "4h": "4 hours, more independent",
}
DEFAULT_REACH_WINDOW = "1h"
