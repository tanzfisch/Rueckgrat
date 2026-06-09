import json
import re
import hashlib
from .common_types import ImageRequest
from typing import Dict, Any, Union
from json_repair import repair_json

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
        
    @classmethod
    def json_loads(cls, text: str):
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if not match:
            return None
        json_str = match.group(1)
        
        try:
            return json.loads(json_str)
        except:
            try:
                repaired = repair_json(json_str)
                return json.loads(repaired)
            except:
                return None    
            
    @classmethod
    def pretty_print(cls, data: Union[Dict[str, Any], str]):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return data
        return json.dumps(data, indent=4).replace('\\n', '\n')