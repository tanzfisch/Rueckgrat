from .job_queue import Job
from .update_context_job import UpdateContextJob
from ..utils.prompt_compiler import PromptCompiler
from typing import Dict, Any
import json
import re
import sys

from app.common import Logger, ChatRequest
logger = Logger(__name__).get_logger()

class ChatJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure

    def execute(self) -> None:
        self.response = self._handle_chat_request(self.request)

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def _remove_code(self, text):
        # Remove triple backtick code blocks
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Remove inline backtick code
        text = re.sub(r"`.*?`", "", text)
        return text.strip()

    def _update_conversation(self, conversation_id: int, assistant_name: str, user_name: str):
        udate_context_job = UpdateContextJob(self.request, self.db, self.infrastructure)
        self.create_and_add(udate_context_job)
        self.wait_for([udate_context_job])
        new_context = udate_context_job.result()
    
        conversation = self.db.get_conversation(conversation_id)
        conversation["title"] = new_context["topic"]
        self.db.update_conversation(conversation_id, conversation["title"], json.dumps(new_context))

    def _cleanup_reply(self, reply: str, name: str):
        prefix = f"{name}: "
        if reply.startswith(prefix):
            return reply.removeprefix(prefix)
        
        return reply

    def _handle_chat_request(self, request: ChatRequest):        
        try:
            contact = self.db.get_contact_by_id(request.contact_id)                
            conversation = self.db.get_conversation(request.conversation_id)

            compiler = PromptCompiler(contact, conversation, request.name)
            system_prompt, context_prompt = compiler.build_prompt()

            logger.debug(f"system_prompt: {system_prompt}")
            logger.debug(f"context_prompt: {context_prompt}")

            payload = [{"role": "system", "content": system_prompt}]
            payload.append({"role": "system", "content": context_prompt})
            
            messages = self.db.get_messages_by_conversation(request.conversation_id, 10)
            for message in messages:
                content = message['content']
                payload.append({"role": message["role"], "content": content})

            size_in_bytes = sys.getsizeof(messages)
            estimated_tokens = size_in_bytes / 4 * 1.25
            logger.debug(f"request from {request.name} estimated token size: {estimated_tokens / 1000}k")

            response_content = self.infrastructure.chat(payload, request.temperature, request.conversation_id)
            if response_content:
                reply = self._cleanup_reply(response_content, contact["name"])
                
                self._update_conversation(request.conversation_id, contact["name"], request.name)
                return {
                    "role": "assistant",
                    "content": reply
                }
            else:
                return {
                    "role": "error",
                    "content": "failed to get chat response"
                }
            
        except Exception as e:
            logger.error(f"failed to handle cheat request {repr(e)}")
