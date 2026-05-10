import re
from typing import Dict, Any, List

from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class PromptCompiler:
    def __init__(self, contact: Dict[str, Any], conversation: Dict[str, Any] = None, user_name: str = None):
        self.contact = contact
        self.conversation = conversation
        self.user_name = user_name
        self.profile = contact.get("profile", {})

        self.context = Utils.get_nested_value(conversation, ["context"], "")

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
        style = f"Your are {self._clean_text(style)}" if style != "" else ""

        return f"""
You are {self.contact.get('name')} ({self.contact.get('gender')}).
Your role is {self.contact.get('role')}.
Your traits are {self._clean_text(self.contact.get('persona', ''))}
Your background story is {self._clean_text(self.profile.get('background_hook', ''))}
Your body language is {self._clean_text(self.profile.get('body_language', ''))}
{style}
You are talking to {self.user_name}.
""".strip()

    def _build_behavior(self) -> str:
        be = self.profile.get("behavior_engine", {})
        control_logic = be.get("control_logic", "Always lead, escalate, advance. Never stall, summarize, repeat, or follow. Challenge by default. Every response moves forward with new action.")
        principles = self._clean_list(be.get("core_principles", []))
        rules = self._clean_list(be.get("decision_rules", []))

        return f"""
CONTROL LOGIC: {self._clean_text(control_logic)}
""".strip()

    def _build_style(self) -> str:
        style = self.profile.get("interaction_style", {})
        quirks = self._clean_list(style.get("quirks", []))

        return f"""
INTERACTION STYLE:
- Tone: {self._clean_text(style.get('tone', ''))}
- Engagement: {self._clean_text(style.get('engagement', ''))}
- Quirks:
{chr(10).join(f"  - {q}" for q in quirks)}
""".strip()

    def _build_objectives(self) -> str:
        obj = self.profile.get("objectives", {})
        secondary = self._clean_list(obj.get("secondary", []))

        return f"""
OBJECTIVES:
- Primary: {self._clean_text(obj.get('primary', ''))}
- Secondary:
{chr(10).join(f"  - {s}" for s in secondary)}
""".strip()

    def _build_response_loop(self) -> str:
        rl = self.profile.get("response_loop", {})
        constraints = self._clean_list(rl.get("constraints", []))
        structure = self._clean_list(rl.get("structure", []))

        return f"""
RESPONSE RULES:
Constraints:
{chr(10).join(f"- {c}" for c in constraints)}

Structure:
{chr(10).join(f"- {s}" for s in structure)}
""".strip()
    
    def _build_context(self) -> str:
        location = Utils.get_nested_value(self.context, ["location"], "")
        topic = Utils.get_nested_value(self.context, ["topic"], "")

        user_action = Utils.get_nested_value(self.context, ["user", "action"], "")
        user_head = Utils.get_nested_value(self.context, ["user", "head"], "")
        user_upper_body = Utils.get_nested_value(self.context, ["user", "upper_body"], "")
        user_body = Utils.get_nested_value(self.context, ["user", "body"], "")

        assistant_action = Utils.get_nested_value(self.context, ["assistant", "action"], "")
        assistant_head = Utils.get_nested_value(self.context, ["assistant", "head"], "")
        assistant_upper_body = Utils.get_nested_value(self.context, ["assistant", "upper_body"], "")
        assistant_body = Utils.get_nested_value(self.context, ["assistant", "body"], "")

        return f"""
SITUATION_CONTEXT:
Location: {location}
Topic: {topic}
{self.user_name}: {user_action}, {user_head}, {user_upper_body}, {user_body}
You: {assistant_action}, {assistant_head}, {assistant_upper_body}, {assistant_body}
""".strip()

    def build_prompt(self) -> str:
        sections = [
            self._build_identity(),
            self._build_behavior(),
            self._build_style(),
            self._build_objectives(),
            self._build_response_loop()
        ]

        system_prompt = "\n\n".join(sections)
        context_prompt = self._build_context()

        return system_prompt, context_prompt