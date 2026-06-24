from app.jobs.job_queue import Job
from typing import Dict,  Any
from abc import abstractmethod

from app.common import get_logger
logger = get_logger()

class Tool(Job):
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

    def result(self) -> Dict[str, Any]:
        return None
    
    def has_response(self) -> bool:
        return False    