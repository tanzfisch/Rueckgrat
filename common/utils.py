import json
import hashlib
from .common_types import ImageRequest
from typing import Any

class Utils:

    @classmethod
    def hash_image_request(cls, obj: ImageRequest) -> str:
        obj_str = json.dumps(obj.model_dump())
        return hashlib.sha256(obj_str.encode()).hexdigest()
    
    @classmethod
    def get_nested_value(cls, data: dict, keys: list[str], default: Any = None):
        current = data
        for key in keys:
            if not isinstance(current, dict):
                return default
            if key not in current:
                return default
            current = current[key]
        return current