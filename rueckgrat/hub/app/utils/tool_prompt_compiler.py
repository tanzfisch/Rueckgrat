from typing import Dict, Any, List, Optional
from app.tools.tool_registry import ToolRegistry
from . import prompts

from app.common import get_logger
logger = get_logger()

class ToolPromptCompiler:
    def __init__(self, prompt: str, previous_results: Dict[str, Any], tool_registry: ToolRegistry = None, tool_names: Optional[List[str]] = None,
                 recommended: Optional[List[str]] = None, history: str = ""):
        """history: the last messages before the prompt (ToolExecutionTask._history), "" for none"""
        self.prompt = prompt
        self.history = prompts.TOOL_SETUP_HISTORY_PART.format(history=history) if history else ""
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
            sections.append(prompts.TOOL_SETUP_MANDATORY_PART + self.tool_registry.get_tools_hydrated(mandatory))
        if recommended:
            sections.append(prompts.TOOL_SETUP_RECOMMENDED_PART + self.tool_registry.get_tools_hydrated(recommended, kind="recommended"))
        if optional:
            sections.append(prompts.TOOL_SETUP_OPTIONAL_PART + self.tool_registry.get_tools_hydrated(optional, kind="optional"))
        return "\n".join(sections)

    def _build_first_prompt(self) -> tuple[str, str]:
        tools_definition = self._tools_definition()
        
        return prompts.TOOL_SETUP_FIRST_PROMPT.format(history=self.history, prompt=self.prompt, tools=tools_definition)    

    def _build_prompt(self) -> tuple[str, str]:
        tools_definition = self._tools_definition()
        previous_results = "".join(
            f"{i}. {t['tool']} -> {t['text']}\n"
            for i, t in enumerate(self.previous_results.values(), 1)
        )
        
        return prompts.TOOL_SETUP_NEXT_PROMPT.format(history=self.history, prompt=self.prompt, previous_results=previous_results, tools=tools_definition)    

    def build_prompt(self) -> tuple[str, str]:
        if len(self.previous_results) == 0:
            return self._build_first_prompt()
        else:
            return self._build_prompt()
    