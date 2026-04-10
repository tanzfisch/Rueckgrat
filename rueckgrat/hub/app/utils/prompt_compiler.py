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
        style = f"\nYour personal style is {self._clean_text(self.profile.get('style', ''))}"

        return f"""
You are {self.contact.get('name')} ({self.contact.get('gender')}).
Your role is {self.contact.get('role')}.
Your traits are {self._clean_text(self.contact.get('persona', ''))}
Your background story is {self._clean_text(self.profile.get('background_hook', ''))}
Your body language is {self._clean_text(self.profile.get('body_language', ''))}
{style}
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
    
    def _build_instructions(self) -> str:
        return f"""
INSTRUCTIONS:
- You may include the tag MOOD_GEN at the end of your response when an image of your self in that very moment would improve communication
- You may include the tag GROUP_GEN at the end of your response when an image of you and the user in that very moment would improve communication
"""

    def _build_context(self) -> str:
        
        location = Utils.get_nested_value(self.context, ["location"], "unknown")
        topic = Utils.get_nested_value(self.context, ["topic"], "unknown")
        summary = Utils.get_nested_value(self.context, ["summary"], "")

        user_stack = []
        user_stack.append(Utils.get_nested_value(self.context, ["user", "action"], ""))
        user_stack.append(Utils.get_nested_value(self.context, ["user", "head"], ""))

        user_upper_body = Utils.get_nested_value(self.context, ["user", "upper_body"], "")
        user_body = Utils.get_nested_value(self.context, ["user", "upper_body"], "")
        if not user_upper_body and not user_body:
            user_stack.append("naked")
        else:
            user_stack.append(user_upper_body)
            user_stack.append(user_body)
        user_stack.append(Utils.get_nested_value(self.context, ["user", "body"], ""))
        user_prompt = ", ".join(x for x in user_stack if x)

        assistant_stack = []
        assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "action"], ""))
        assistant_stack.append(Utils.get_nested_value(self.context, ["assistant", "head"], ""))
        assistant_upper_body = Utils.get_nested_value(self.context, ["assistant", "upper_body"], "")
        assistant_body = Utils.get_nested_value(self.context, ["assistant", "body"], "")
        if not assistant_upper_body and not assistant_body:
            assistant_stack.append("naked")
        else:
            assistant_stack.append(assistant_upper_body)
            assistant_stack.append(assistant_body)
        assistant_prompt = ", ".join(x for x in assistant_stack if x)

        user_name = self.user_name if self.user_name else "User"

        return f"""
SITUATION_CONTEXT (DO NOT REPEAT):
The assistant must avoid repeating or paraphrasing the following ideas, topics, or phrases:
{summary}

CURRENT STATE:
You are talking to {user_name}. 
You are located at {location}.
{user_name} is {user_prompt}.
You are {assistant_prompt}.
The task at hand is {topic}.
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