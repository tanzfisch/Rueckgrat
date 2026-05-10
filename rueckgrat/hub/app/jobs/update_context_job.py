from .job_queue import Job
from typing import Dict, Any
import json
import re
import random

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
            conversation = self.db.get_conversation(self.request.conversation_id)
            context = Utils.get_nested_value(conversation, ["context"], "")
            messages = self.db.get_messages_by_conversation(self.request.conversation_id, 6)
            self.updated_context = self._update_context(context, messages)
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

    def _update_context(self, context: str, messages: list):
        messages_block = "\n".join([
            f'- "{self._remove_code(m["content"])}" (role: {m["role"]})'
            for m in messages
        ])

        if context == "":
            # fallback context
            context = """
            {
                "location": "unkonwn"
                "topic": "unkonwn",

                "user": {
                "action": "unknown",
                "head": "",
                "upper_body": "casual t-shirt",
                "body": "jeans and comfortable shoes"
                },

                "assistant": {
                "action": "unknown",
                "head": "",
                "upper_body": "casual t-shirt",
                "body": "jeans and comfortable shoes"
                }
            }
            """

            query = f"""
            Create a new context for a conversation.

            MESSAGES:
            {messages_block}

            EXAMPLE CONTEXT:
            {{
                "location": "Paris",
                "topic": "sight seeing",

                "user": {{
                    "action": "standing and looking around",
                    "head": "",
                    "upper_body": "casual t-shirt",
                    "body": "jeans and comfortable shoes",
                }},

                "assistant": {{
                    "action": "pointing towards a landmark",
                    "head": "sunglasses on head, light beard",
                    "upper_body": "light button-up shirt with rolled sleeves",
                    "body": "cargo pants and sturdy walking shoes",
                }}
            }}

            INSTRUCTIONS:
            - Invent a situation where user and assistant found them selves in while including the given messages as well
            - Fill in information as applicable
            - Keep ALL fields SHORT (max 40 words each)
            - "topic" = 1 short phrase
            - "user"/"assistant"-"action" = intent, body position, activity, gestures, facial expression, emotions, NOT dialogue
            - "user"/"assistant"-"head" = items this person is wearing on the head
            - "user"/"assistant"-"upper_body" = items this person is wearing specifically on the upper body
            - "user"/"assistant"-"body" = items this person is wearing on the body (not carrying)
            - "location" = environment or setting

            OUTPUT:
            Return ONLY valid JSON in the given format.
            """
        else:
            query = f"""
            You maintain a running context for a conversation.

            NEW MESSAGES:
            {messages_block}

            CURRENT CONTEXT:
            {{
                "location": "{context['location']}",
                "topic": "{context['topic']}",
                "summary": "",

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
            - Ammend but only if it does not create redundancy
            - Keep ALL fields SHORT (max 40 words each)
            - Keep only the MOST IMPORTANT and RECENT info
            - DROP anything irrelevant or outdated
            - "topic" = 1 short phrase
            - "user"/"assistant"-"action" = intent, body position, activity, gestures, facial expression, emotions, NOT dialogue
            - "user"/"assistant"-"head" = items this person is wearing on the head
            - "user"/"assistant"-"upper_body" = items this person is wearing specifically on the upper body
            - "user"/"assistant"-"body" = items this person is wearing on the body (not carrying)
            - "location" = environment, setting, only if explicitly mentioned
            - "summary" = write a detailed summary of the whole conversation and put it here (max 300 words)

            OUTPUT:
            Return ONLY valid JSON in the same format.
            """

        payload = [{"role": "user", 
                    "content": query}]
        
        response_content = self.infrastructure.chat(payload, 0.0, random.randint(0, 100000), True)
        if response_content:
            match = re.search(r"```json\s*(.*?)\s*```", response_content, re.DOTALL)
            if not match:
                logger.error("failed to generate new context")
                return context
            
            try:                
                reply = json.loads(match.group(1))
            except Exception as e:
                logger.error(f"failed to load json: {e}")            

            # making sure we can guarantee a certain json structure
            new_context = {
                "location": Utils.get_nested_value(reply, ["location"], "unknown"),
                "topic": Utils.get_nested_value(reply, ["topic"], "unknown"),
                "summary": Utils.get_nested_value(reply, ["summary"], ""),

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

            logger.debug(f"new context:\n{json.dumps(new_context, indent=4)}")

            return new_context
        else:
            logger.warning(f"failed to update context")
            return context
    