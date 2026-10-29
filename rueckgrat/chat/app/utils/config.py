import configparser
import os
from pathlib import Path

from app.common import get_logger, Utils
logger = get_logger()


class RueckgratConfig:
    DEFAULTS = {
        "hub": {
            "rueckgrat_hub_host": "rueckgrat.hub",
            "rueckgrat_hub_port": "443"
        },
        "chat": {
            "log_level": "DEBUG"
        }
    }

    def _config_path(self) -> Path:
        data = os.getenv("FLET_APP_STORAGE_DATA")
        if data:
            return Path(data) / "rueckgrat.conf"
        return Path.home() / ".config/Rueckgrat/rueckgrat.conf"

    def __init__(self, ):
        self.config_path=self._config_path()

        self.found_config = False
        self.config = configparser.ConfigParser()
        logger.info(f"Reading config from {self.config_path}")

        self._ensure_file()
        self._load()

    def has_config(self):
        return self.found_config

    def _ensure_file(self):
        """Create config file with defaults if it doesn't exist."""
        if not self.config_path.exists():            
            logger.info("Config file not found, creating with defaults")

            if not self.config_path.parent.exists():
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                # only the folder we create here; existing ones (e.g. ~/.config) are left as they are
                self._chmod(self.config_path.parent, 0o700)

            # Write default config
            for section, values in self.DEFAULTS.items():
                self.config[section] = values

            self._write()

            if not self.config_path.exists():            
                logger.error(f"failed to write config to {self.config_path}")
        else:
            self.found_config = True

    @staticmethod
    def _chmod(path, mode):
        """best effort: some platforms (Android storage) don't do unix modes"""
        try:
            os.chmod(path, mode)
        except OSError as e:
            logger.debug(f"chmod {oct(mode)} {path} failed: {e}")

    def _write(self):
        """write the config owner read/write only: it holds the session token (stay logged in)"""
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(self.config_path, flags, 0o600)  # mode applies when the file is created
        try:
            os.fchmod(fd, 0o600)  # an existing file keeps its old mode otherwise
        except (OSError, AttributeError) as e:
            logger.debug(f"chmod 0o600 {self.config_path} failed: {e}")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            self.config.write(f)

    def _load(self):
        """Load config from file."""
        # files written by older versions were world readable
        if os.name == "posix" and self.config_path.stat().st_mode & 0o077:
            self._chmod(self.config_path, 0o600)
        with open(self.config_path, encoding="utf-8-sig") as f:
            self.config.read_file(f)

    def _save(self):
        """Persist current config back to disk."""
        self._write()
        logger.debug("writing config file")

    def _get(self, section, key, fallback=None):
        return self.config.get(section, key, fallback=fallback)

    def _set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = str(value)
        self._save()

    # --- Properties ---

    @property
    def host(self):
        return self._get("hub", "rueckgrat_hub_host", "localhost")

    @host.setter
    def host(self, value):
        self._set("hub", "rueckgrat_hub_host", value)

    @property
    def port(self):
        return self._get("hub", "rueckgrat_hub_port", "443")

    @port.setter
    def port(self, value):
        self._set("hub", "rueckgrat_hub_port", value)

    @property
    def log_level(self):
        return self._get("chat", "log_level", "ERROR")

    @property
    def refresh_token(self):
        """the stored session (stay logged in), "" when logged out"""
        return self._get("session", "refresh_token", "")

    @refresh_token.setter
    def refresh_token(self, value):
        self._set("session", "refresh_token", value or "")

    _LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}

    @log_level.setter
    def log_level(self, value):
        name = str(value).upper()
        if name not in _LEVELS:
            raise ValueError(f"invalid log level: {value}")
        self._set("chat", "log_level", name)