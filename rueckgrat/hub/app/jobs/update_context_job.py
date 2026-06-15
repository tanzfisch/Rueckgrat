from .job_queue import Job
from typing import Dict, Any
import json
import re
import random
from ..utils.prompt_compiler import PromptCompiler

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
        try:
            messages_block = "\n".join([
                f'- "{self._remove_code(m["content"])}" (role: {m["role"]})'
                for m in messages
            ])

            payload = []
            contact = self.db.get_contact_by_id(self.request.contact_id)
            conversation = self.db.get_conversation(self.request.conversation_id)
            compiler = PromptCompiler(contact, conversation, self.request.name)
            system_prompt, context_prompt = compiler.build_prompt()

            payload.append({"role": "developer", "content": system_prompt})

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
- Invent a detailed narrative situation where user and assistant are immersed together, with the given messages as central, heavily weighted dialogue, plot drivers, and key exchanges.
- Fill in information as applicable
- Keep ALL fields SHORT (max 40 words each)
- an empty string is perfectly valid and means the absence of things or actions
- topic = 1 short phrase about what is happening
- user|assistant/action = intent, body position, activity, gestures, facial expression, emotions, NOT dialogue
- user|assistant/head = items this person is wearing on the head
- user|assistant/upper_body = items this person is wearing specifically on the upper body or carrying in their hands
- user|assistant/body = items this person is wearing on the body
- location = environment or setting

OUTPUT:
Return ONLY valid JSON in the given format.
"""
            else:
                query = f"""
You maintain a running context for a conversation.

LATEST MESSAGES:
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
- figure out the latest state of the conversation and update the current context
- focus on removing and adding items if mentioned in the conversation
- do not invent items or actions
- if an item was transfered between people remove it from the source
- keep the information consitent, avoid redundancies or conflicting statements
- Keep ALL fields SHORT (max 40 words each)
- an empty string is perfectly valid and means the absence of things or actions
- there is two people relevant in this conversation the user and the assistant identify which is which and update accordingly
- topic = 1 short phrase about what is happening
- user|assistant/action = intent, body position, activity, gestures, facial expression, emotions, NOT dialogue
- user|assistant/head = items this person is wearing on the head
- user|assistant/upper_body = items this person is wearing specifically on the upper body or carrying in their hands
- user|assistant/body = items this person is wearing on the body
- location = environment or setting
- summary = write a detailed summary of the whole conversation and put it here (max 300 words)

OUTPUT:
Return ONLY valid JSON in the same format.
"""

            logger.debug(f"update context query:\n{query}")
            payload.append({"role": "user", "content": query})
        except Exception as e:
            logger.error(f"failed to build query {repr(e)}")            
        
        response_content = self.infrastructure.chat(payload, 0.4, random.randint(0, 100000), True)
        if not response_content:
            logger.warning(f"failed to update context")
            return context
        
        reply = Utils.json_loads(response_content)
        if not reply:
            logger.error(f"failed to generate new context from:\n{response_content}") 
            return context

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

    