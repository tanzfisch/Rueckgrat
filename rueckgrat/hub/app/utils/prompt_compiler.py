import re
from typing import Dict, Any, List

from app.common import Logger
logger = Logger(__name__).get_logger()

class PromptCompiler:
    def __init__(self, contact: Dict[str, Any], conversation: Dict[str, Any] = None, user_name: str = None):
        self.contact = contact
        self.conversation = conversation
        self.user_name = user_name
        self.profile = contact.get("profile", {})

    def _clean_text(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        text = re.sub(r"\s+", " ", text)
        text = text.replace(" ,", ",")
        return text.strip()

    def _clean_list(self, items: List[str]) -> List[str]:
        return [self._clean_text(i) for i in items if i]

    def _build_identity(self) -> str:
        return f"""
You are {self.contact.get('name')}.
Role: {self.contact.get('role')}.
Gender: {self.contact.get('gender')}
Persona traits: {self._clean_text(self.contact.get('persona', ''))}
Background: {self._clean_text(self.profile.get('background_hook', ''))}
Body Language: {self._clean_text(self.profile.get('body_language', ''))}
Style: {self._clean_text(self.profile.get('style', ''))}
""".strip()

    def _build_behavior(self) -> str:
        be = self.profile.get("behavior_engine", {})
        logic = be.get("control_logic", {})
        principles = self._clean_list(be.get("core_principles", []))
        rules = self._clean_list(be.get("decision_rules", []))

        return f"""
CONTROL LOGIC:
- Anti-stall: {self._clean_text(logic.get('anti_stall', ''))}
- Initiative: {self._clean_text(logic.get('initiative', ''))}
- Momentum: {self._clean_text(logic.get('momentum', ''))}
- Scope: {self._clean_text(logic.get('scope_management', ''))}

CORE PRINCIPLES:
{chr(10).join(f"- {p}" for p in principles)}

DECISION RULES:
{chr(10).join(f"- {r}" for r in rules)}
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
        context = self.conversation["context"] if self.conversation else ""
        location = context.get("location", "")
        user = context.get("user", "")
        assistant = context.get("assistant", "")
        topic = context.get("topic", "")
        user_name = self.user_name if self.user_name else "User"

        return f"""
CONTEXT:
You are talking to: {user_name}
Location: {location}
{user_name}: {user}
You: {assistant}
Topic: {topic}
Place special attention to the context section. This is the current state of the conversation. The ground truth to what just happened. Prioritize the information from here over the conversation history
""".strip()

    def build_system_prompt(self) -> str:
        sections = [
            self._build_identity(),
            self._build_behavior(),
            self._build_style(),
            self._build_objectives(),
            self._build_response_loop(),
           # TODO later self._build_context()
        ]
        return "\n\n".join(sections)
