import re
from typing import Dict, Any, List
from datetime import datetime

from . import prompts

from app.common import get_logger, Utils
logger = get_logger()

def build_context(user_name, context, summary: str = "") -> str:
    """the situation of the conversation. summary: the nightly summary of the conversation so far, left out when empty.
    without a context yet (before the first update) only the summary"""
    if not context:
        return prompts.CONVERSATION_SO_FAR_PART.format(summary=summary) if summary else ""
    location = Utils.get_nested_value(context, ["location"], "")
    topic = Utils.get_nested_value(context, ["topic"], "")

    user_action = Utils.get_nested_value(context, ["user", "action"], "")
    user_head = Utils.get_nested_value(context, ["user", "head"], "")
    user_upper_body = Utils.get_nested_value(context, ["user", "upper_body"], "")
    user_body = Utils.get_nested_value(context, ["user", "body"], "")

    assistant_action = Utils.get_nested_value(context, ["assistant", "action"], "")
    assistant_head = Utils.get_nested_value(context, ["assistant", "head"], "")
    assistant_upper_body = Utils.get_nested_value(context, ["assistant", "upper_body"], "")
    assistant_body = Utils.get_nested_value(context, ["assistant", "body"], "")

    return prompts.SITUATION_CONTEXT_PART.format(
        location=location, topic=topic, user_name=user_name,
        user_action=user_action, user_head=user_head, user_upper_body=user_upper_body, user_body=user_body,
        assistant_action=assistant_action, assistant_head=assistant_head, assistant_upper_body=assistant_upper_body, assistant_body=assistant_body,
        conversation_so_far=prompts.CONVERSATION_SO_FAR_PART.format(summary=summary) if summary else "").strip()

class PromptCompiler:
    def __init__(self, contact: Dict[str, Any], conversation: Dict[str, Any] = None, user_role_name: str = None):
        self.contact = contact
        self.conversation = conversation
        self.user_role_name = user_role_name
        self.profile = contact.get("profile", {})

        self.context = Utils.get_nested_value(conversation, ["context"], "")
        self.summary = Utils.get_nested_value(conversation, ["summary"], "") or ""

    def _clean_text(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        text = re.sub(r"\s+", " ", text)
        text = text.replace(" ,", ",")
        return text.strip()

    def _clean_list(self, items: List[str]) -> List[str]:
        return [self._clean_text(i) for i in items if i]

    def _build_identity(self) -> str:
        style = self.profile.get('style', '')
        style = prompts.IDENTITY_STYLE_PART.format(style=self._clean_text(style)) if style != "" else ""

        name = Utils.get_nested_value(self.contact, ["identity", "name"], "")
        gender = Utils.get_nested_value(self.contact, ["identity", "gender"], "")
        role = Utils.get_nested_value(self.contact, ["identity", "role"], "")
        personality = self._clean_text(Utils.get_nested_value(self.contact, ["identity", "personality"], ""))

        background_hook = self._clean_text(Utils.get_nested_value(self.profile, ["background_hook"], ""))
        relationship = self._clean_text(Utils.get_nested_value(self.profile, ["relationship"], ""))
        body_language = self._clean_text(Utils.get_nested_value(self.profile, ["body_language"], ""))

        return prompts.IDENTITY_PART.format(
            name=name, gender=gender, role=role, personality=personality, background_hook=background_hook,
            body_language=body_language, style=style, user_role_name=self.user_role_name, relationship=relationship).strip()

    def _build_behavior(self) -> str:
        return prompts.CONTROL_LOGIC_PART.strip()

    def _build_style(self) -> str:
        style = self.profile.get("interaction_style", {})
        quirks = self._clean_list(style.get("quirks", []))
        
        if str(self.profile.get("sfw", "")).lower() == "sfw":
            sfw = prompts.PERSONA_SFW_PART
        else:
            sfw = prompts.PERSONA_UNRESTRICTED_PART 

        return prompts.INTERACTION_STYLE_PART.format(
            tone=self._clean_text(style.get('tone', '')), engagement=self._clean_text(style.get('engagement', '')), sfw=sfw,
            quirks=chr(10).join(f"  - {q}" for q in quirks)).strip()

    def _build_objectives(self) -> str:
        obj = self.profile.get("objectives", {})
        secondary = self._clean_list(obj.get("secondary", []))

        return prompts.OBJECTIVES_PART.format(
            primary=self._clean_text(obj.get('primary', '')), secondary=chr(10).join(f"  - {s}" for s in secondary)).strip()
   
    def _build_instructions(self) -> str:
        return prompts.INSTRUCTIONS_PART

    @staticmethod
    def date_time() -> str:
        return prompts.LOCAL_TIME_PART.format(now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    def build_prompt(self) -> tuple[str, str]:
        sections = []

        sections.append(self._build_identity())
        sections.append(self._build_behavior())
        sections.append(self._build_style())
        sections.append(self._build_objectives())
        sections.append(self._build_instructions())
        situation = [self.date_time(), build_context(self.user_role_name, self.context, self.summary)]

        system_prompt = "\n\n".join(sections)

        return system_prompt, "\n\n".join(s for s in situation if s)