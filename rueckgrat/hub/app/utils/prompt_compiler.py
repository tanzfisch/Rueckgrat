import re
from typing import Dict, Any, List


class PromptCompiler:
    def __init__(self, config: Dict[str, Any], user_name: str):
        self.config = config
        self.user_name = user_name
        self.profile = config.get("profile", {})

    # --------- Utilities ---------
    def _clean_text(self, text: str) -> str:
        """Normalize broken spacing and commas."""
        if not isinstance(text, str):
            return text
        text = re.sub(r"\s+", " ", text)
        text = text.replace(" ,", ",")
        return text.strip()

    def _clean_list(self, items: List[str]) -> List[str]:
        return [self._clean_text(i) for i in items if i]

    # --------- Core Sections ---------
    def _build_identity(self) -> str:
        return f"""
You are {self.config.get('name')}.
Role: {self.config.get('role')}.
Gender: {self.config.get('gender')}
Persona traits: {self._clean_text(self.config.get('persona', ''))}
Background: {self._clean_text(self.profile.get('background_hook', ''))}
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
    
    def _build_conversation_partner(self) -> str:
        return f"""
You are talking to: {self.user_name}
""".strip()

    # --------- Public API ---------
    def build(self) -> str:
        sections = [
            self._build_identity(),
            self._build_behavior(),
            self._build_style(),
            self._build_objectives(),
            self._build_response_loop(),
            self._build_conversation_partner()
        ]

        return "\n\n".join(sections)

    def get_llm_parameters(self) -> Dict[str, Any]:
        return self.profile.get("llm_parameters", {})

    def get_image_parameters(self) -> Dict[str, Any]:
        return self.profile.get("image_parameters", {})

    def get_tts_parameters(self) -> Dict[str, Any]:
        return self.profile.get("tts_parameters", {})