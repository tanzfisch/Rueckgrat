from .job_queue import Job
from ..utils.prompt_compiler import PromptCompiler
from typing import Dict, Any
import json
import re
from urllib.parse import urlparse

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
        self.stream_id = None

    def execute(self) -> None:
        try:            
            contact = self.db.get_contact_by_id(self.request.contact_id)
            conversation = self.db.get_conversation(self.request.conversation_id)

            compiler = PromptCompiler(
                contact=contact,
                conversation=conversation,
                user_role_name=self.request.name,
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
                if not content:
                    continue    # skip if empty to not confuse ai
                if message["role"] == "assistant":
                    content += self._tools_line(message.get("tools"))
                    content += self._sources_line(message.get("sources"))
                messages.append({"role": message["role"], "content": content})

            if self.thinking_response:
                logger.debug("adding tool outputs to chat query")
                messages.append({"role": "developer", "content": self.thinking_response})
            
            self.stream_id = self.infrastructure.chat(
                messages=messages,
                temperature=self.request.temperature,
                seed=self.request.conversation_id,
                stream=True,
                callback=self.callback
            )
        except Exception as e:
            logger.error(f"failed to handle chat request {repr(e)}")

    @staticmethod
    def _tools_line(tools) -> str:
        """one short line naming the tools a past answer used, so the model knows what it did"""
        names = [tool for tool in tools if isinstance(tool, str)] if isinstance(tools, list) else []
        return f"\n(tools used: {', '.join(names)})" if names else ""

    @staticmethod
    def _sources_line(sources) -> str:
        """one short line naming the domains a past answer used, so the model knows its sources"""
        domains = []
        for source in sources if isinstance(sources, list) else []:
            url = source.get("url") if isinstance(source, dict) else None
            domain = urlparse(url).netloc.lower().removeprefix("www.") if isinstance(url, str) else ""
            if domain and domain not in domains:
                domains.append(domain)
        return f"\n(sources: {', '.join(domains)})" if domains else ""

    def result(self) -> Dict[str, Any]:
        return None

    def has_response(self) -> bool:
        return False