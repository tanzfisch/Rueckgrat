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
        if self.context == "":
            self.context = Utils.get_nested_value(contact, ["profile", "start_context"], "")        

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
    
    def _build_instructions(self) -> str:
        return f"""
TOOLS:
- If you feel like it, add the tag MOOD_GEN at the end of your response to generate a picture of yourself in the current situation.
"""

    def _build_context(self) -> str:
        summary = Utils.get_nested_value(self.context, ["summary"], "")

        if not summary:
            return ""

        return f"""
SITUATION_CONTEXT (DO NOT REPEAT):
Never reference, paraphrase, or allude to any part of the following summary: {summary}
""".strip()

    def build_prompt(self) -> str:
        sections = [
            self._build_identity(),
            self._build_behavior(),
            self._build_style(),
            self._build_objectives(),
            self._build_response_loop(),            
            self._build_instructions()
        ]

        system_prompt = "\n\n".join(sections)
        context_prompt = self._build_context()

        return system_prompt, context_prompt