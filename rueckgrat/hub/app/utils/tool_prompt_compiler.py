from datetime import datetime
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from app.tools.tool_registry import ToolRegistry
from . import prompts

from app.common import get_logger
logger = get_logger()

class ToolPromptCompiler:
    def __init__(self, prompt: str, previous_results: Dict[str, Any], tool_registry: ToolRegistry = None, tool_names: Optional[List[str]] = None,
                 recommended: Optional[List[str]] = None, history: str = "", scope: Optional[Dict[str, int]] = None,
                 timezone: Optional[ZoneInfo] = None, excluded: tuple = ()):
        """history: the last messages before the prompt (ToolExecutionTask._history), "" for none. scope: {user_id,
        contact_id, conversation_id} of the setup, for the tools' prompt_for (None: their plain prompt). timezone: the
        user's (clock.user_timezone), the setup knows what "today" and "my time" are. None: not told. excluded: the
        tools this setup can't use, no note names them (ToolRegistry.notes)"""
        self.prompt = prompt
        self.history = prompts.TOOL_SETUP_HISTORY_PART.format(history=history) if history else ""
        self.time = prompts.TOOL_SETUP_TIME_PART.format(timezone=timezone.key, now=datetime.now(timezone).strftime("%A, %Y-%m-%d %H:%M")) \
            if timezone else ""
        self.previous_results = previous_results
        self.tool_names = tool_names
        self.recommended = list(recommended or [])
        self.tool_registry = tool_registry
        self.scope = scope
        self.excluded = tuple(excluded)

    def _tools_definition(self) -> str:
        """the surely detected tools must be called, the recommended ones and the optional ones (PROMPT_TOOLS: remember,
        search_memory, take_photo; companions: share_file) the model decides about. then how they work together with
        the other tools (ToolRegistry.notes)"""
        mandatory, recommended, optional = self.tool_registry.split_tools(self.tool_names, self.recommended)
        sections = []
        if mandatory:
            sections.append(prompts.TOOL_SETUP_MANDATORY_PART + self.tool_registry.get_tools_hydrated(mandatory, scope=self.scope))
        if recommended:
            sections.append(prompts.TOOL_SETUP_RECOMMENDED_PART + self.tool_registry.get_tools_hydrated(recommended, kind="recommended", scope=self.scope))
        if optional:
            sections.append(prompts.TOOL_SETUP_OPTIONAL_PART + self.tool_registry.get_tools_hydrated(optional, kind="optional", scope=self.scope))
        notes = self.tool_registry.notes(mandatory + recommended + optional, self.excluded)
        if notes:
            sections.append(notes)
        return "\n".join(sections)

    def _build_first_prompt(self) -> tuple[str, str]:
        tools_definition = self._tools_definition()
        
        return prompts.TOOL_SETUP_FIRST_PROMPT.format(history=self.history, time=self.time, prompt=self.prompt, tools=tools_definition)    

    def _build_prompt(self) -> tuple[str, str]:
        tools_definition = self._tools_definition()
        lines = filter(None, (self._result_line(name, result) for name, result in self.previous_results.items()))
        previous_results = "".join(f"{i}. {line}\n" for i, line in enumerate(lines, 1))
        
        return prompts.TOOL_SETUP_NEXT_PROMPT.format(history=self.history, time=self.time, prompt=self.prompt, previous_results=previous_results, tools=tools_definition)    

    @staticmethod
    def _result_line(name: str, result: Any) -> str:
        """one earlier result for the next round: "tool -> text", a failed call with its error so the round can do
        better, "" for a result without text (an image, sources only)"""
        if not isinstance(result, dict):
            return ""
        tool = result.get("tool", name)
        if result.get("error"):
            return f"{tool} -> failed: {result['error']}"
        return f"{tool} -> {result['text']}" if result.get("text") else ""

    def build_prompt(self) -> tuple[str, str]:
        if len(self.previous_results) == 0:
            return self._build_first_prompt()
        else:
            return self._build_prompt()
    