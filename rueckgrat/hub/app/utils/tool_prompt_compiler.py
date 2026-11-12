from typing import Dict, Any, List, Optional
from app.tools.tool_registry import ToolRegistry

from app.common import get_logger
logger = get_logger()

class ToolPromptCompiler:
    def __init__(self, prompt: str, previous_results: Dict[str, Any], tool_registry: ToolRegistry = None, tool_names: Optional[List[str]] = None,
                 recommended: Optional[List[str]] = None):
        self.prompt = prompt
        self.previous_results = previous_results
        self.tool_names = tool_names
        self.recommended = list(recommended or [])
        self.tool_registry = tool_registry

    def _tools_definition(self) -> str:
        """the surely detected tools must be called, the recommended ones and the PROMPT_TOOLS (remember, search_memory,
        take_photo) the model decides about"""
        mandatory, recommended, optional = self.tool_registry.split_tools(self.tool_names, self.recommended)
        sections = []
        if mandatory:
            sections.append("MANDATORY TOOLS\n" + self.tool_registry.get_tools_hydrated(mandatory))
        if recommended:
            sections.append("RECOMMENDED TOOLS\n" + self.tool_registry.get_tools_hydrated(recommended, kind="recommended"))
        if optional:
            sections.append("OPTIONAL TOOLS\n" + self.tool_registry.get_tools_hydrated(optional, kind="optional"))
        return "\n".join(sections)

    def _build_first_prompt(self) -> tuple[str, str]:
        tools_definition = self._tools_definition()
        
        return f"""
This is a tool setup run. Apply given tools based on the original prompt.

ORIGINAL PROMPT
{self.prompt}

GIVEN TOOLS TO APPLY NEXT
{tools_definition}
"""    

    def _build_prompt(self) -> tuple[str, str]:
        tools_definition = self._tools_definition()
        previous_results = "".join(
            f"{i}. {t['tool']} -> {t['text']}\n"
            for i, t in enumerate(self.previous_results.values(), 1)
        )
        
        return f"""
This is a tool setup run. Apply given tools based on the original prompt and results from previous tool calls.

ORIGINAL PROMPT
{self.prompt}

PREVIOUS TOOL CALL RESULTS
{previous_results}

GIVEN TOOLS TO APPLY NEXT
{tools_definition}
"""    

    def build_prompt(self) -> tuple[str, str]:
        if len(self.previous_results) == 0:
            return self._build_first_prompt()
        else:
            return self._build_prompt()
    