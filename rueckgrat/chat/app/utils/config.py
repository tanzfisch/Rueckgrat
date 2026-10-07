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
            "log_level": "ERROR"
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

            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Write default config
            for section, values in self.DEFAULTS.items():
                self.config[section] = values

            with open(self.config_path, "w", encoding="utf-8") as f:
                self.config.write(f)

            if not self.config_path.exists():            
                logger.error(f"failed to write config to {self.config_path}")
        else:
            self.found_config = True

    def _load(self):
        """Load config from file."""
        with open(self.config_path, encoding="utf-8-sig") as f:
            self.config.read_file(f)

    def _save(self):
        """Persist current config back to disk."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            self.config.write(f)
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

    _LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}

    @log_level.setter
    def log_level(self, value):
        name = str(value).upper()
        if name not in _LEVELS:
            raise ValueError(f"invalid log level: {value}")
        self._set("chat", "log_level", name)