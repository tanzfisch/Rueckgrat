"""
Hub settings changed at runtime, by hub management (docker exec ... python -m app.hub_management), without a restart.
One small json file in the hub's db volume, read again on every get: the hub's watchers pick a change up on their next round.
A key that is not in the file falls back to its environment variable (.env, written by the installer), a key set to ""
is switched off on purpose (also when .env has a value).
"""
import json
import os
import threading
from pathlib import Path
from typing import Optional

from app.common import get_logger
logger = get_logger()

SETTINGS_PATH = Path("/hub/db/hub_settings.json")


class HubSettings:
    """get/set/clear of the runtime settings. ENV: the environment variable each key falls back to"""
    ENV = {"nomad_url": "NOMAD_URL"}

    def __init__(self, path: Path = SETTINGS_PATH):
        self._path = Path(path)
        self._lock = threading.Lock()

    def path(self) -> Path:
        return self._path

    def get(self, key: str) -> str:
        """the file's value, else the environment variable's, else "" """
        value = self.stored(key)
        if value is not None:
            return value
        return os.environ.get(self.ENV.get(key, ""), "").strip() if key in self.ENV else ""

    def stored(self, key: str) -> Optional[str]:
        """the value in the file, None when the file does not set key"""
        value = self._read().get(key)
        return None if value is None else str(value)

    def source(self, key: str) -> str:
        """where get(key) comes from: "hub settings", "environment" or "not set" """
        if self.stored(key) is not None:
            return "hub settings"
        return "environment" if key in self.ENV and os.environ.get(self.ENV[key], "").strip() else "not set"

    def set(self, key: str, value: str) -> None:
        """value "" switches the setting off, also against the environment variable"""
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def reset(self, key: str) -> None:
        """removes key from the file, the environment variable counts again"""
        with self._lock:
            data = self._read()
            if key in data:
                del data[key]
                self._write(data)

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.error(f"hub settings {self._path} not readable: {e!r}")
            return {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
