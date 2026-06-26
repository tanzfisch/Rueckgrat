import configparser
import os
from pathlib import Path

from app.common import get_logger, Utils
logger = get_logger()


class RueckgratConfig:
    DEFAULTS = {
        "hub": {
            "rueckgrat_hub_host": "localhost",
            "rueckgrat_hub_port": "443"
        }
    }

    def __init__(self, ):
        if Utils.is_docker():
            self.config_path=Path("/config/rueckgrat.conf").expanduser()
        else:
            self.config_path=Path("~/.config/Rueckgrat/rueckgrat.conf").expanduser()

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