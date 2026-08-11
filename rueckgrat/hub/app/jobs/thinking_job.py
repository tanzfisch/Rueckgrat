from .job_queue import Job
from typing import Dict, Any
import json
import random
from ..utils.prompt_compiler import PromptCompiler

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class ThinkingJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure, tool_registry):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry

    def execute(self) -> None:
        self.thinking_response = self._thinking(self.request)

    def result(self) -> Dict[str, Any]:
        return self.thinking_response
      
    def _thinking(self, request: ChatRequest):
        try:
            contact = self.db.get_contact_by_id(request.contact_id)
            conversation = self.db.get_conversation(request.conversation_id)

            compiler = PromptCompiler(
                contact=contact, 
                conversation=conversation, 
                user_name=request.name, 
                thinking=True,
                tool_registry=self.tool_registry
            )

            system_prompt, context_prompt = compiler.build_prompt()
            messages = [{"role": "developer", "content": system_prompt}]
            if context_prompt:
                messages.append({"role": "developer", "content": context_prompt})
            
            #history = self.db.get_messages_by_conversation(request.conversation_id, 2)
            #for message in history:
            #    content = message['content']
            #    messages.append({"role": message["role"], "content": content})

            query = f"""
THINKING ONLY
Quickly break down query. Note key context/needs. Spot gaps, use tools if needed. Plan answer structure.
Output tool call first if required, then short analysis + plan only. No final response.

THE QUERY
{request.content}
"""            
            messages.append({"role": "user", "content": query})

            response_content = self.infrastructure.chat(
                messages=messages,
                temperature=0.3,
                seed=random.randint(0, 100000)
            )

            tool_calls, content = self.tool_registry.extract_tool_calls(response_content)
            return {
                "content": content,
                "tool_calls": tool_calls
            }            

        except Exception as e:
            logger.error(f"failed to think {repr(e)}")       

    