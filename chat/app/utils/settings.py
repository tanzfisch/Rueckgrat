import os
from PySide6.QtCore import QSettings, QStandardPaths

class Settings:
    config_path = QStandardPaths.writableLocation(
        QStandardPaths.ConfigLocation
    )
    settings_file = os.path.join(config_path, "Rueckgrat", "chat.conf")
    print(f"load settings from {settings_file}")
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    _settings = QSettings(settings_file, QSettings.IniFormat)

    @classmethod
    def set_value(cls, key, value):
        cls._settings.setValue(key, value)

    @classmethod
    def get_value(cls, key, default=None):
        return cls._settings.value(key, default)
