import json
import re
import hashlib
from .common_types import ImageRequest
from typing import Dict, Any, Union
from json_repair import repair_json

from .logger import get_logger
logger = get_logger()

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
            logger.error("failed to find json match in text")
            return None
        
        json_str = match.group(1)        
        try:
            return json.loads(json_str)
        except:
            try:
                logger.warning("trying to repair json")
                repaired = repair_json(json_str)
                return json.loads(repaired)
            except:
                logger.warning(f"failed to load json from {text}")
                return None    
            
    @classmethod
    def pretty_print_full(cls, data: Union[Dict[str, Any], str]):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return data
        return json.dumps(data, indent=4).replace('\\n', '\n')

    @classmethod
    def pretty_print(cls, data: Union[Dict[str, Any], str], max_len: int = 500):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return data[:max_len] + "..." if len(data) > max_len else data

        def truncate(obj):
            if isinstance(obj, str):
                return obj[:max_len] + "..." if len(obj) > max_len else obj
            if isinstance(obj, dict):
                return {k: truncate(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [truncate(item) for item in obj]
            return obj

        return json.dumps(truncate(data), indent=4).replace('\\n', '\n')

    @classmethod
    def pretty_scores(cls, data: dict[str, float], bar_width: int = 20, thresholds: tuple[float, float] = (0.4, 0.7)) -> str:
        if not data:
            return "(empty)"
        max_key = max(len(k) for k in data)
        low, high = (int(t * bar_width) for t in thresholds)
        zones = ((0, low, 31), (low, high, 33), (high, bar_width, 32))
        lines = []
        for k, v in data.items():
            filled = max(0, min(bar_width, int(v * bar_width)))
            bar = "█" * filled
            for start, end, colour in zones:
                unfilled = "░" * max(0, end - max(start, filled))
                if unfilled:
                    bar += f"\033[{colour}m{unfilled}\033[0m"
            lines.append(f"{k:<{max_key}}  {v:7.4f}  {bar}")
        return "\n".join(lines)

    @classmethod
    def shorten(cls, s: str, max_len: int = 40) -> str:
        if len(s) <= max_len:
            return s
        keep = max_len - 3
        left = keep // 2
        return f"{s[:left]}...{s[-(keep - left):]}"
