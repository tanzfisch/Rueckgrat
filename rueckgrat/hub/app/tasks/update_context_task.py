from .task_queue import Task
from typing import Dict, Any
import re
import json
import random

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

_PERSON_SCHEMA = {
    "type": "object",
    "properties": {key: {"type": "string"} for key in ("action", "head", "upper_body", "body")},
    "required": ["action", "head", "upper_body", "body"],
}

class UpdateContextTask(Task):
    # the reply's shape, llama.cpp only lets the model write json like this (compact, no indentation)
    CONTEXT_SCHEMA = {
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "topic": {"type": "string"},
            "user": _PERSON_SCHEMA,
            "assistant": _PERSON_SCHEMA,
        },
        "required": ["location", "topic", "user", "assistant"],
    }
    MAX_NEW_TOKENS = 300    # ten short fields
    # where a conversation starts: nothing known yet, the first update fills in what the messages show
    EMPTY_CONTEXT = {
        "location": "", "topic": "",
        "user": {"action": "", "head": "", "upper_body": "", "body": ""},
        "assistant": {"action": "", "head": "", "upper_body": "", "body": ""},
    }

    def __init__(self, request: ChatRequest, db, infrastructure):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.updated_context = None

    def execute(self) -> None:
        """runs after the reply: updates the conversation's context from the last exchange and stores it with
        its topic as title, the next turn uses it. nobody waits for this"""
        try:
            conversation = self.db.get_conversation(self.request.conversation_id)
            context = Utils.get_nested_value(conversation, ["context"], "") or self.EMPTY_CONTEXT
            messages = self.db.get_messages_by_conversation(self.request.conversation_id, 2)
            self.updated_context = self._update_context(context, messages)
            if self.updated_context:
                title = self.updated_context["topic"] or Utils.get_nested_value(conversation, ["title"], "...")
                self.db.update_conversation(self.request.conversation_id, title, json.dumps(self.updated_context))
        except Exception as e:
            logger.error(f"failed to update context {repr(e)}")

    def get_result(self) -> Dict[str, Any]:
        return self.updated_context
    
    def _remove_code(self, text):
        # Remove triple backtick code blocks
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Remove inline backtick code
        text = re.sub(r"`.*?`", "", text)
        return text.strip()
    
    def _update_context(self, context: str, messages: list):
        try:
            messages_block = "\n".join([
                f'- "{self._remove_code(m["content"])}" (role: {m["role"]})'
                for m in messages
            ])

            messages = []

            # stable rules first, the changing parts last, so llama.cpp can reuse the cached prefix
            query = f"""
Update the scene context after the latest messages. "user" wrote the (role: user) messages, "assistant" the (role: assistant) ones, never swap them.

RULES:
- change only what the messages show, invent nothing
- an item handed over moves to the other person
- "" means nothing there
- each field at most 15 words
- location: the setting. topic: one short phrase
- action: posture, activity, gesture, expression, mood, not speech
- head: worn on the head. upper_body: worn on the upper body or held. body: worn on the rest of the body

CURRENT CONTEXT:
{json.dumps(context, ensure_ascii=False)}

LATEST MESSAGES:
{messages_block}

Reply with the JSON only, same keys.
"""            
            messages.append({"role": "user", "content": query})
        except Exception as e:
            logger.error(f"failed to build query {repr(e)}")            
                
        response_content = self.infrastructure.chat(
            messages=messages,
            temperature=0.4,
            seed=random.randint(0, 100000),
            max_new_tokens=self.MAX_NEW_TOKENS,
            json_schema=self.CONTEXT_SCHEMA
        )
        if not response_content:
            logger.warning("failed to update context")
            return None

        reply = Utils.json_loads(response_content)
        if not reply:
            logger.error(f"failed to generate new context from:\n{response_content}")
            return None

        # making sure we can guarantee a certain json structure
        new_context = {
            "location": Utils.get_nested_value(reply, ["location"], "unknown"),
            "topic": Utils.get_nested_value(reply, ["topic"], "unknown"),

            "user": {
                "action": Utils.get_nested_value(reply, ["user", "action"], ""),
                "head": Utils.get_nested_value(reply, ["user", "head"], ""),
                "upper_body": Utils.get_nested_value(reply, ["user", "upper_body"], "casual t-shirt"),
                "body": Utils.get_nested_value(reply, ["user", "body"], "jeans and comfortable shoes"),
            },

            "assistant": {
                "action": Utils.get_nested_value(reply, ["assistant", "action"], ""),
                "head": Utils.get_nested_value(reply, ["assistant", "head"], ""),
                "upper_body": Utils.get_nested_value(reply, ["assistant", "upper_body"], "casual t-shirt"),
                "body": Utils.get_nested_value(reply, ["assistant", "body"], "jeans and comfortable shoes"),
            }
        }

        #logger.debug(f"new context:\n{Utils.pretty_print(new_context)}")

        return new_context

    