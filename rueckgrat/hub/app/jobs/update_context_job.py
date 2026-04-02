from .job_queue import Job
from typing import Dict, Any
import json
import re

from app.common import Logger, ChatRequest, Utils
logger = Logger(__name__).get_logger()

class UpdateContextJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure

    def execute(self) -> None:
        try:
            contact = self.db.get_contact_by_id(self.request.contact_id)
            conversation = self.db.get_conversation(self.request.conversation_id)
            context = Utils.get_nested_value(conversation, ["context"], "")
            if context == "":
                context = Utils.get_nested_value(contact, ["profile", "start_context"], "")
            messages = self.db.get_messages_by_conversation(self.request.conversation_id, 4)

            assistant_name = contact["name"]
            user_name = self.request.name
            self.updated_context = self._update_context(context, messages, assistant_name, user_name)
        except Exception as e:
            logger.error(f"failed to update context {repr(e)}")


    def result(self) -> Dict[str, Any]:
        return self.updated_context
    
    def _remove_code(self, text):
        # Remove triple backtick code blocks
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Remove inline backtick code
        text = re.sub(r"`.*?`", "", text)
        return text.strip()

    def _update_context(self, context, messages: list, assistant_name: str, user_name: str):
        messages_block = "\n".join([
            f'- "{self._remove_code(m["content"])}" (role: {m["role"]})'
            for m in messages
        ])

        query = f"""
        You maintain a running context for a conversation.

        NEW MESSAGES:
        {messages_block}

        CURRENT CONTEXT:
        {{
            "location": "{context['location']}",
            "topic": "{context['topic']}",

            "user": {{
                "action": "{context['user']['action']}",
                "head": "{context['user']['head']}",
                "upper_body": "{context['user']['upper_body']}",
                "body": "{context['user']['body']}",
            }},

            "assistant": {{
                "action": "{context['assistant']['action']}",
                "head": "{context['assistant']['head']}",
                "upper_body": "{context['assistant']['upper_body']}",
                "body": "{context['assistant']['body']}",
            }}
        }}

        INSTRUCTIONS:
        - Process messages in order (top = oldest, bottom = newest)
        - Update information if possible and overwrite if necessary
        - Ammend if information is important
        - Keep ALL fields SHORT (max 40 words each)
        - Keep only the MOST IMPORTANT and RECENT info
        - DROP anything irrelevant or outdated
        - "topic" = 1 short phrase
        - "user"/"assistant" - "action" = intent, body position, activity, gestures, facial expression, emotions, NOT dialogue
        - "user"/"assistant" - "head" = items this person is wearing on the head
        - "user"/"assistant" - "upper_body" = items this person is wearing on the upper body
        - "user"/"assistant" - "body" = items this person is wearing but neither on the head nor upper body
        - "location" = environment, setting, only if explicitly mentioned

        OUTPUT:
        Return ONLY valid JSON in the same format.
        """
        payload = [{"role": "user", 
                    "content": query}]
        
        response_content = self.infrastructure.chat(payload, 0.0, True)
        if response_content:
            match = re.search(r"```json\s*(.*?)\s*```", response_content, re.DOTALL)
            if not match:
                return context
            
            try:                
                reply = json.loads(match.group(1))
            except Exception as e:
                logger.error(f"failed to load json: {e}")            

            new_context = {
                "location": Utils.get_nested_value(reply, ["location"]),
                "topic": Utils.get_nested_value(reply, ["topic"]),

                "user": {
                    "action": Utils.get_nested_value(reply, ["user", "action"]),
                    "head": Utils.get_nested_value(reply, ["user", "head"]),
                    "upper_body": Utils.get_nested_value(reply, ["user", "upper_body"]),
                    "body": Utils.get_nested_value(reply, ["user", "body"]),
                },

                "assistant": {
                    "action": Utils.get_nested_value(reply, ["assistant", "action"]),
                    "head": Utils.get_nested_value(reply, ["assistant", "head"]),
                    "upper_body": Utils.get_nested_value(reply, ["assistant", "upper_body"]),
                    "body": Utils.get_nested_value(reply, ["assistant", "body"]),
                }
            }

            logger.debug(f"new_context {json.dumps(new_context, indent=4)}")

            return new_context
        else:
            logger.warning(f"failed to update context")
            return context
    