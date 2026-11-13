import time
import json
from .task_queue import Task
from typing import Dict, Any, List, Optional, Callable
from ..utils.tool_prompt_compiler import ToolPromptCompiler
from ..utils.prompt_compiler import build_context
from ..utils.trace import Trace
from ..tools import prompts as tool_prompts

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class ToolExecutionTask(Task):
    def __init__(self, user_id: int, request: ChatRequest, context, db, infrastructure, tool_registry, tool_names: List[str],
                 message_id: int = None, excluded_tools: tuple = (), llm_timeout: Optional[float] = None,
                 recommended_tools: List[str] = (), detach: Optional[Callable[[], bool]] = None,
                 tool_calls: Optional[List[Dict[str, Any]]] = None, fix_rounds: int = 0):
        """tool_names must be called, recommended_tools (the detection was not sure) the model decides about, like the
        PROMPT_TOOLS. a mandatory PRIORITY_TOOL is the only tool, a recommended one runs on its own, first or after
        the detected mandatory tools (registry.rounds).
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
        self.fix_rounds = fix_rounds    # a worker's: more passes of the FIX_TOOLS while their calls fail (_fix), 0 for a chat turn
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
            problems: List[str] = []
            for round, tools in enumerate(ranked_groups, 1):
                logger.debug(f"tool execution ({round}/{len(ranked_groups)}): {', '.join(tools)}"
                             + (f" (recommended: {', '.join(t for t in tools if t in self.recommended)})" if any(t in self.recommended for t in tools) else ""))
                tool_calls, found = self._round(f"{round}/{len(ranked_groups)}", tools, self.recommended, self.request.content)
                problems += found
                if any(call.get("tool") == self.tool_registry.PRIORITY_TOOL for call in tool_calls):
                    logger.debug(f"{self.tool_registry.PRIORITY_TOOL} was called, it is the only tool")
                    break
            else:
                self._fix(problems)

            logger.debug(f"execution task results:\n{Utils.pretty_print(self.tool_response)}")

        except Exception as e:
            logger.error(f"failed to direct tools {repr(e)}")

    def _round(self, label: str, tools: List[str], recommended: List[str], prompt_text: str) -> tuple[List[Dict[str, Any]], List[str]]:
        """one tool setup: one llm call writes the calls of tools (prompt_text: the task, with the earlier results), they run
        together and their results go into tool_response. returns (the calls that ran, what went wrong that a fix round
        could repair: failed calls, a cut off reply)"""
        compiler = ToolPromptCompiler(prompt_text, self.tool_response, self.tool_registry, tools, recommended)
        messages = []
        context_prompt = build_context(self.request.name, self.context) if self.context else ""
        if context_prompt:
            messages.append({"role": "developer", "content": context_prompt})
        messages.append({"role": "user", "content": compiler.build_prompt()})
        #logger.debug(f"tool setup prompt:\n{Utils.pretty_print_full(messages)}")

        conversation_id = self.request.conversation_id
        Trace.write(conversation_id, f"setup round {label} prompt", Trace.messages(messages), tools=tools,
                    recommended=[t for t in tools if t in recommended], max_new_tokens=self.infrastructure.long_reply_tokens())
        started, info = time.monotonic(), {}
        response_content = self.infrastructure.chat(
            messages=messages,
            temperature=0.0,
            seed=1337,
            max_new_tokens=self.infrastructure.long_reply_tokens(),
            timeout=self.llm_timeout,
            info=info
        )
        Trace.write(conversation_id, f"setup round {label} raw reply", response_content or "", no_reply=response_content is None,
                    chars=len(response_content or ""), seconds=f"{time.monotonic() - started:.1f}", **info)

        parsed, content = self.tool_registry.extract_tool_calls(response_content)
        tool_calls = [call for call in parsed or [] if call.get("tool") in tools]
        grounding = f"{prompt_text}\n{json.dumps(self.tool_response, ensure_ascii=False, default=str)}"
        made_up = [call for call in tool_calls if call.get("tool") in recommended and not self.tool_registry.grounded(call, grounding)]
        if made_up:
            logger.warning(f"dropped recommended calls with no value from the message: {made_up}")
            tool_calls = [call for call in tool_calls if call not in made_up]
        # a last call max_new_tokens cut, or calls missing after the llm's length limit
        cut_off = self.tool_registry.cut_off_result(response_content, tools, length=info.get("finish_reason") == "length")
        Trace.write(conversation_id, f"setup round {label} calls", f"TEXT OUTSIDE THE CALLS:\n{content}" if content else "",
                    parse_failed=parsed is None, parsed=[call.get("tool") for call in parsed or []], run=len(tool_calls),
                    dropped_not_offered=[call.get("tool") for call in parsed or [] if call.get("tool") not in tools],
                    dropped_made_up=made_up or None,
                    cut_off=list(cut_off or []))
        if cut_off:
            logger.warning(f"setup reply cut off ({info.get('finish_reason') or 'unclosed call'}), {', '.join(cut_off)} calls missing")
        problems = [f"{name}: {note['text']}" for name, note in (cut_off or {}).items() if name in self.tool_registry.FIX_TOOLS]
        if self.fix_rounds:
            problems += self.tool_registry.not_called([t for t in tools if t not in recommended], tool_calls)
        results = self._run(tool_calls) if tool_calls else None
        self.tool_registry.merge_results(self.tool_response, cut_off)
        return tool_calls, self.tool_registry.problems(results) + problems

    def _fix(self, problems: List[str]) -> None:
        """a worker's fix rounds (fix_rounds, 0: none): while bash, run_code or write_file calls failed, were cut off or
        files were not attached, those tools get one more pass with the results so far and what went wrong, at most
        fix_rounds times. a "checks" result tells the reply the final state, so it does not claim that what failed works"""
        tools = [name for name in self.tool_registry.FIX_TOOLS if name in self.tool_names + self.recommended]
        if not self.fix_rounds or not tools or not problems:
            return
        conversation_id, fix = self.request.conversation_id, 0
        while problems and fix < self.fix_rounds:
            fix += 1
            logger.info(f"fix round {fix}/{self.fix_rounds}: {'; '.join(problems)[:300]}")
            Trace.write(conversation_id, f"fix round {fix}/{self.fix_rounds}", "\n".join(problems), tools=tools)
            prompt = self.request.content + tool_prompts.FIX_ROUND_PART.format(
                fix=fix, total=self.fix_rounds, problems="\n".join(f"- {problem}" for problem in problems))
            problems = []
            for group in self.tool_registry.ranked_groups(tools):    # bash and run_code, then write_file
                problems += self._round(f"fix {fix}/{self.fix_rounds}", group, group, prompt)[1]
        text = tool_prompts.CHECKS_FAILED_PART.format(rounds=fix, problems="; ".join(problems)) if problems \
            else tool_prompts.CHECKS_FIXED_PART.format(rounds=fix)
        self.tool_response["checks"] = {"tool": "checks", "text": text}
        logger.info(f"fix rounds done: {text[:300]}")
        Trace.write(conversation_id, "checks", text, fix_rounds=fix, still_failing=len(problems))

    def _run(self, tool_calls: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """runs the calls together, their results go into tool_response. returns them ({tool name: result}, None for none)"""
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
        return tool_call_result

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
