import time
from .task_queue import Task
from typing import Dict, Any, List, Optional, Callable
from ..utils.tool_prompt_compiler import ToolPromptCompiler
from ..utils.prompt_compiler import build_context

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

SETUP_TOKENS = 4096

class ToolExecutionTask(Task):
    def __init__(self, user_id: int, request: ChatRequest, context, db, infrastructure, tool_registry, tool_names: List[str],
                 message_id: int = None, excluded_tools: tuple = (), llm_timeout: Optional[float] = None,
                 recommended_tools: List[str] = (), detach: Optional[Callable[[], bool]] = None,
                 tool_calls: Optional[List[Dict[str, Any]]] = None):
        """tool_names must be called, recommended_tools (the detection was not sure) the model decides about, like the
        PROMPT_TOOLS. a mandatory PRIORITY_TOOL is the only tool, a recommended one runs first on its own (registry.rounds).
        tool_calls: run these as they are instead, without a tool setup (the calls a chat reply wrote)"""
        super().__init__()
        self.user_id = user_id
        self.request = request
        self.context = context
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.excluded_tools = tuple(excluded_tools)
        mandatory, recommended = tool_registry.bands(tool_registry.available(list(tool_names or []) + tool_registry.PROMPT_TOOLS, self.excluded_tools),
                                                     tool_registry.available(recommended_tools, self.excluded_tools))
        self.tool_names = mandatory
        self.recommended = recommended
        self.message_id = message_id
        self.detach = detach    # ToolRegistry.execute: lets the DETACHED_TOOLS calls run in the background
        self.llm_timeout = llm_timeout
        self.tool_calls = tool_calls
        self.tool_response = {}
        self.executed: List[Dict[str, Any]] = []    # {"call", "ms"} per call that ran, in order. the calls of a round run together and share its time

    def get_result(self) -> Dict[str, Any]:
        return self.tool_response
      
    def execute(self) -> None:
        try:
            if self.tool_calls is not None:
                logger.debug(f"tool execution of given calls: {', '.join(call.get('tool', '?') for call in self.tool_calls)}")
                self._run(self.tool_calls)
                return

            ranked_groups = self.tool_registry.rounds(self.tool_names, self.recommended)
            for round, tools in enumerate(ranked_groups, 1):
                logger.debug(f"tool execution ({round}/{len(ranked_groups)}): {', '.join(tools)}"
                             + (f" (recommended: {', '.join(t for t in tools if t in self.recommended)})" if any(t in self.recommended for t in tools) else ""))
                compiler = ToolPromptCompiler(self.request.content, self.tool_response, self.tool_registry, tools, self.recommended)
                prompt = compiler.build_prompt()

                messages = []

                context_prompt = build_context(self.request.name, self.context) if self.context else ""
                if context_prompt:
                    messages.append({"role": "developer", "content": context_prompt})

                messages.append({"role": "user", "content": prompt})
                #logger.debug(f"tool setup prompt:\n{Utils.pretty_print_full(messages)}")

                response_content = self.infrastructure.chat(
                    messages=messages,
                    temperature=0.0,
                    seed=1337,
                    max_new_tokens=SETUP_TOKENS,
                    timeout=self.llm_timeout
                )

                tool_calls, content = self.tool_registry.extract_tool_calls(response_content)
                tool_calls = [call for call in tool_calls or [] if call.get("tool") in tools]
                if not tool_calls:
                    continue

                self._run(tool_calls)
                if any(call.get("tool") == self.tool_registry.PRIORITY_TOOL for call in tool_calls):
                    logger.debug(f"{self.tool_registry.PRIORITY_TOOL} was called, it is the only tool")
                    break

            logger.debug(f"execution task results:\n{Utils.pretty_print(self.tool_response)}")

        except Exception as e:
            logger.error(f"failed to direct tools {repr(e)}")

    def _run(self, tool_calls: List[Dict[str, Any]]) -> None:
        """runs the calls together, their results go into tool_response"""
        start = time.monotonic()
        tool_call_result = self.tool_registry.execute(
            user_id=self.user_id,
            contact_id=self.request.contact_id,
            conversation_id=self.request.conversation_id,
            tool_calls=[dict(call, llm_timeout=self.llm_timeout) if self.llm_timeout else call for call in tool_calls],
            message_id=self.message_id,
            excluded=self.excluded_tools,
            detach=self.detach
        )
        ms = int((time.monotonic() - start) * 1000)
        self.executed += [{"call": call, "ms": ms} for call in tool_calls]
        if tool_call_result:
            self.tool_registry.merge_results(self.tool_response, tool_call_result)

    @staticmethod
    def results_prompt(results: Dict[str, Dict[str, Any]]) -> str:
        """the TOOL_RESULTS block of the results for a reply prompt, failed tools left out. "" without results"""
        if not results:
            return ""
        lines = []
        for r in results.values():
            tool = r.get("tool", "unknown")
            if "error" in r:
                continue
            lines.append(f"{tool}: {r.get('text', '')}")

        return "\nTOOL_RESULTS\n" + "\n".join(lines) + "\n"
