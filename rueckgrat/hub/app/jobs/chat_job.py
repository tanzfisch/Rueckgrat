from .job_queue import Job
from ..utils.prompt_compiler import PromptCompiler
from typing import Dict, Any
import json
import re

from app.common import get_logger, ChatRequest
logger = get_logger()

class ChatJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure, callback=None, thinking_response = None):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.thinking_response = thinking_response
        self.callback = callback

    def execute(self) -> None:
        try:            
            contact = self.db.get_contact_by_id(self.request.contact_id)
            conversation = self.db.get_conversation(self.request.conversation_id)

            compiler = PromptCompiler(
                contact=contact,
                conversation=conversation,
                user_name=self.request.name,
                thinking=False,
                tool_registry=None
            )

            system_prompt, context_prompt = compiler.build_prompt()

            messages = [{"role": "developer", "content": system_prompt}]
            if context_prompt:
                messages.append({"role": "developer", "content": context_prompt})
            
            history = self.db.get_messages_by_conversation(self.request.conversation_id, 10)
            for message in history:
                content = message['content']
                messages.append({"role": message["role"], "content": content})

            if self.thinking_response:
                logger.debug("adding tool outputs to chat query")
                messages.append({"role": "developer", "content": self.thinking_response})
            
            self.infrastructure.chat(
                messages=messages,
                temperature=self.request.temperature,
                seed=self.request.conversation_id,
                stream=True,
                callback=self.callback
            )
        except Exception as e:
            logger.error(f"failed to handle chat request {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return None

    def has_response(self) -> bool:
        return False