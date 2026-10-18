from app.jobs.job_queue import Job
from typing import Dict,  Any
from abc import abstractmethod
import json
import re

from app.common import get_logger
logger = get_logger()

class ToolCategory:
    """the tool categories, one place for all of them. a tool sets its own with `category = ToolCategory.X`"""
    WEB = "web"            # looks things up on the internet
    MEDIA = "media"        # creates images (and later audio/video)
    MATH = "math"          # numbers: conversions, calculations
    TIME = "time"          # clock, time zones, dates
    GENERAL = "general"    # default for tools that don't set a category

class Tool(Job):
    category = ToolCategory.GENERAL
    description = ""    # one line for the tool index, every tool sets its own

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__()
        self.db = db
        self.infrastructure = infrastructure
        self.user_id=user_id
        self.contact_id=contact_id
        self.conversation_id=conversation_id
        self.response=response
        self.tool_call=tool_call

    @classmethod
    def name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def prompt(cls) -> str:
        raise NotImplementedError

    @classmethod
    def example(cls) -> str:
        """the call format as single line json, one line per example in prompt(). override for a custom example"""
        lines = []
        for block in re.findall(r'\{[^{}]*"tool"\s*:\s*"' + re.escape(cls.name()) + r'"[^{}]*\}', cls.prompt()):
            try:
                lines.append(json.dumps(json.loads(block), ensure_ascii=False))
            except ValueError:
                lines.append(" ".join(block.split()))
        return "\n".join(lines) or json.dumps({"tool": cls.name()})

    @classmethod
    def get_description(cls) -> str:
        """the one line for the tool index. fallback: first prompt line that is not a "HEADER:" line"""
        if cls.description:
            return cls.description
        for line in cls.prompt().splitlines():
            line = line.strip()
            if line and not line.endswith(":"):
                return line
        return cls.name()

    def result(self) -> Dict[str, Any]:
        return None
    
    def has_response(self) -> bool:
        return False    