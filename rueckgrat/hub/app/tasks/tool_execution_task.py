import time
import traceback
import json
from .task_queue import Task
from typing import Dict, Any, List, Optional, Callable, Tuple
from ..utils.tool_prompt_compiler import ToolPromptCompiler
from ..utils.prompt_compiler import build_context
from ..utils.trace import Trace
from ..utils.clock import user_timezone
from ..tools import prompts as tool_prompts

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class ToolExecutionTask(Task):
    FIND_TOOLS = "find_tools"   # its calls ask for another detection, their tools get extra rounds (_find_tools)
    FIND_TOOLS_STEPS = 2        # how often in a row the extra rounds can find more tools
    HISTORY_CHARS = 1500        # an earlier message in the setup prompt is cut after this, the prompt stays short

    def __init__(self, user_id: int, request: ChatRequest, context, db, infrastructure, tool_registry, tool_names: List[str],
                 message_id: int = None, excluded_tools: tuple = (), llm_timeout: Optional[float] = None,
                 recommended_tools: List[str] = (), detach: Optional[Callable[[], bool]] = None,
                 tool_calls: Optional[List[Dict[str, Any]]] = None, fix_rounds: int = 0, history: int = 0, background: bool = False):
        super().__init__(user_id=user_id)
        self.request = request
        self.context = context
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.excluded_tools = tuple(excluded_tools)
        self.tool_names, self.recommended = self._bands(list(tool_names or []) + tool_registry.PROMPT_TOOLS, recommended_tools)
        self.message_id = message_id
        self.detach = detach    # ToolRegistry.execute: lets the DETACHED_TOOLS calls run in the background
        self.llm_timeout = llm_timeout
        self.background = background    # an agent job's, task's or companion pass's: its calls carry it (Tool.background)
        self.tool_calls = tool_calls
        self.history = history          # how many messages before this turn's the setup sees (_history), 0 for a worker
        self.history_text: Optional[str] = None
        self.fix_rounds = fix_rounds    # a worker's: more passes of the fixable tools while their calls fail (_fix), 0 for a chat turn
        self._failing: List[Tuple[str, str]] = []   # (tool name, problem) still there at the end (failing)
        self.tool_response = {}
        self.executed: List[Dict[str, Any]] = []    # {"call", "ms"} per call that ran, in order. the calls of a round run together and share its time

    def _bands(self, mandatory: List[str], recommended: List[str]) -> tuple[List[str], List[str]]:
        """(mandatory, recommended) of a detection, without the excluded tools (ToolRegistry.bands). the companions of
        the offered tools (share_file with bash) join the mandatory ones, the setup offers them as optional (split_tools)"""
        mandatory, recommended = self.tool_registry.bands(self.tool_registry.available(mandatory, self.excluded_tools),
                                                          self.tool_registry.available(recommended, self.excluded_tools))
        return mandatory + self.tool_registry.companions(mandatory + recommended, self.excluded_tools), recommended

    def get_result(self) -> Dict[str, Any]:
        return self.tool_response

    def _history(self) -> str:
        """the last self.history messages before this turn's, with what the answers showed (a poll and its choice, a map):
        the setup sees that a quiz goes on when the user's message is only its answer. read once per task"""
        if self.history_text is None:
            self.history_text = ""
            if self.history and self.db:
                from .chat_task import ChatTask     # chat_task imports this module
                messages = [message for message in self.db.get_messages_by_conversation(self.request.conversation_id, self.history + 8) or []
                            if message.get("role") in ("user", "assistant") and message.get("id") != self.message_id]
                while messages and messages[-1]["role"] == "user":
                    messages.pop()      # this turn's message, and the follow-ups merged into it
                blocks = []
                for message in messages:
                    content = (message.get("content") or "").strip()
                    if len(content) > self.HISTORY_CHARS:
                        content = content[:self.HISTORY_CHARS] + " ..."
                    if message["role"] == "assistant":
                        content = (content + ChatTask._data_lines(message.get("data") or {})).strip()
                    if content:
                        blocks.append(f"{message.get('name') or message['role']}: {content}")
                self.history_text = "\n\n".join(blocks[-self.history:])
        return self.history_text
      
    def execute(self) -> None:
        try:
            if self.tool_calls is not None:
                logger.debug(f"tool execution of given calls: {', '.join(call.get('tool', '?') for call in self.tool_calls)}")
                self._run(self.tool_calls)
                return

            problems, requests = self._rounds(self.tool_names, self.recommended, self.request.content)
            self._failing = problems
            if requests is not None:
                problems += self._find_tools(requests)
                self._failing = self._fix(problems)

            logger.debug(f"execution task results:\n{Utils.pretty_print(self.tool_response)}")

        except Exception as e:
            logger.error(f"failed to direct tools {repr(e)}\n{traceback.format_exc()}")

    def _rounds(self, mandatory: List[str], recommended: List[str], prompt_text: str, step: str = "",
                also: List[str] = ()) -> tuple[List[Tuple[str, str]], Optional[List[Dict[str, Any]]]]:
        """the rounds of a tool setup (ToolRegistry.rounds), also: optional tools offered in the last round (no round of
        their own). returns (what a fix round could repair, the find_tools calls), None for the calls when one of the
        PRIORITY_TOOLS was called: nothing runs after it (ToolRegistry.ends_setup)"""
        ranked_groups = self.tool_registry.rounds(mandatory, recommended)
        if ranked_groups and also:
            ranked_groups[-1] += [name for name in also if name not in ranked_groups[-1]]
        problems: List[Tuple[str, str]] = []
        requests: List[Dict[str, Any]] = []
        for round, tools in enumerate(ranked_groups, 1):
            label = f"{step}{round}/{len(ranked_groups)}"
            logger.debug(f"tool execution ({label}): {', '.join(tools)}"
                         + (f" (recommended: {', '.join(t for t in tools if t in recommended)})" if any(t in recommended for t in tools) else ""))
            tool_calls, found = self._round(label, tools, recommended, prompt_text)
            problems += found
            requests += [call for call in tool_calls if call.get("tool") == self.FIND_TOOLS]
            priority = self.tool_registry.ends_setup(tool_calls)
            if priority:
                logger.debug(f"{priority} was called, nothing runs after it")
                return problems, None
        return problems, requests

    def _find_tools(self, requests: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """the find_tools calls: a detection on their tasks, the tools it finds that were not offered yet get extra rounds
        (with find_tools again, at most FIND_TOOLS_STEPS in a row). returns what a fix round could repair"""
        from .tool_detection_task import ToolDetectionTask     # tool_detection_task imports the task package too
        problems: List[Tuple[str, str]] = []
        step = 0
        while requests and step < self.FIND_TOOLS_STEPS:
            step += 1
            task = "; ".join(dict.fromkeys(filter(None, (self.tool_registry.tools[self.FIND_TOOLS].task(call) for call in requests))))
            if not task:
                break
            detection = ToolDetectionTask(task, self.tool_registry, self.infrastructure, excluded_tools=self.excluded_tools)
            self.tool_registry.task_queue.run(detection)
            detection.trace(self.request.conversation_id, f"find_tools {step}/{self.FIND_TOOLS_STEPS}")
            # a tool offered already is not offered again: the poll would be asked twice
            detected = self._bands(detection.tool_names or [], detection.recommended or [])
            offered = set(self.tool_names + self.recommended)
            mandatory, recommended = ([name for name in band if name not in offered] for band in detected)
            found, detected = mandatory + recommended, detected[0] + detected[1]
            logger.info(f"find_tools {step}/{self.FIND_TOOLS_STEPS}: {task[:200]} -> {detected or 'nothing'}, new: {found}")
            text = tool_prompts.FIND_TOOLS_FOUND_PART.format(task=task, tools=", ".join(found)) if found \
                else tool_prompts.FIND_TOOLS_OFFERED_PART.format(task=task, tools=", ".join(detected)) if detected \
                else tool_prompts.FIND_TOOLS_NONE_PART.format(task=task)
            self.tool_response[self.FIND_TOOLS] = {"tool": self.FIND_TOOLS, "text": text}
            if not found:
                break
            self.tool_names += [name for name in mandatory if name not in self.tool_names]
            self.recommended += [name for name in recommended if name not in self.recommended]
            again = [self.FIND_TOOLS] if step < self.FIND_TOOLS_STEPS and self.FIND_TOOLS not in self.excluded_tools else []
            found_problems, requests = self._rounds(mandatory, recommended,
                                                    self.request.content + tool_prompts.FIND_TOOLS_ROUND_PART.format(task=task),
                                                    step=f"find {step} ", also=again)
            problems += found_problems
        return problems

    def _round(self, label: str, tools: List[str], recommended: List[str], prompt_text: str) -> tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
        """one tool setup: one llm call writes the calls of tools (prompt_text: the task, with the earlier results), they run
        together and their results go into tool_response. returns (the calls that ran, what went wrong that a fix round
        could repair: (tool name, problem) of failed calls, a cut off reply)"""
        compiler = ToolPromptCompiler(prompt_text, self.tool_response, self.tool_registry, tools, recommended,
                                      history=self._history(),
                                      scope={"user_id": self.get_user_id(), "contact_id": self.request.contact_id,
                                             "conversation_id": self.request.conversation_id},
                                      timezone=self._timezone(), excluded=self.excluded_tools)
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
        made_up = [call for call in tool_calls if call.get("tool") in recommended and not self.tool_registry.grounded(call, grounding, conversation_id)]
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
        fixable = self.tool_registry.fixable(list(cut_off or {}))
        problems = [(name, f"{name}: {note['text']}") for name, note in (cut_off or {}).items() if name in fixable]
        if self.fix_rounds:
            problems += self.tool_registry.not_called([t for t in tools if t not in recommended], tool_calls)
        results = self._run(tool_calls) if tool_calls else None
        self.tool_registry.merge_results(self.tool_response, cut_off)
        return tool_calls, self.tool_registry.problems(results) + problems

    def _timezone(self):
        """the user's timezone for the setup prompt (clock.user_timezone), None without a user or db"""
        return user_timezone(self.db, self.get_user_id()) if self.db is not None and self.get_user_id() is not None else None

    def failing(self) -> List[Tuple[str, str]]:
        """(tool name, problem) of what still went wrong when the task ended: after a worker's fix rounds, or of its
        rounds when there were none (a chat turn)"""
        return list(self._failing)

    def _fix(self, problems: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """a worker's fix rounds (fix_rounds, 0: none): while calls of the fixable tools (Tool.fixable) failed, were cut
        off or files were not attached, those tools get one more pass with the results so far and what went wrong, at
        most fix_rounds times. a problem of a tool that did not run again in a round stays (nothing fixed it). a "checks"
        result tells the reply the final state, so it does not claim that what failed works. returns the problems left"""
        tools = self.tool_registry.fixable(self.tool_names + self.recommended)
        if not self.fix_rounds or not tools or not problems:
            return problems
        conversation_id, fix = self.request.conversation_id, 0
        while problems and fix < self.fix_rounds:
            fix += 1
            texts = [text for _, text in problems]
            logger.info(f"fix round {fix}/{self.fix_rounds}: {'; '.join(texts)[:300]}")
            Trace.write(conversation_id, f"fix round {fix}/{self.fix_rounds}", "\n".join(texts), tools=tools)
            prompt = self.request.content + tool_prompts.FIX_ROUND_PART.format(
                fix=fix, total=self.fix_rounds, problems="\n".join(f"- {text}" for text in texts))
            found: List[Tuple[str, str]] = []
            called = set()
            for group in self.tool_registry.ranked_groups(tools):    # in TOOL_ORDER: bash, run_code and share_file before write_file
                calls, group_problems = self._round(f"fix {fix}/{self.fix_rounds}", group, group, prompt)
                called |= {call.get("tool") for call in calls}
                found += group_problems
            problems = [problem for problem in problems if problem[0] not in called] + found
        texts = list(dict.fromkeys(text for _, text in problems))
        text = tool_prompts.CHECKS_FAILED_PART.format(rounds=fix, problems="; ".join(texts)) if problems \
            else tool_prompts.CHECKS_FIXED_PART.format(rounds=fix)
        self.tool_response["checks"] = {"tool": "checks", "text": text}
        logger.info(f"fix rounds done: {text[:300]}")
        Trace.write(conversation_id, "checks", text, fix_rounds=fix, still_failing=len(problems),
                    failing_tools=sorted({name for name, _ in problems}) or None)
        return problems

    def _call(self, call: Dict[str, Any]) -> Dict[str, Any]:
        """the call as the tool gets it: with the llm timeout of an agent job, and background only when this task's (not the llm's)"""
        call = {key: value for key, value in call.items() if key != "background"}
        if self.llm_timeout:
            call["llm_timeout"] = self.llm_timeout
        if self.background:
            call["background"] = True
        return call

    def _run(self, tool_calls: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """runs the calls together, their results go into tool_response. returns them ({tool name: result}, None for none)"""
        start = time.monotonic()
        tool_call_result = self.tool_registry.execute(
            user_id=self.get_user_id(),
            contact_id=self.request.contact_id,
            conversation_id=self.request.conversation_id,
            tool_calls=[self._call(call) for call in tool_calls],
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
    def results_prompt(results: Dict[str, Dict[str, Any]], failed: bool = True) -> str:
        """the TOOL_RESULTS block of the results for a reply prompt. a failed tool keeps its text (what failed, so the
        reply does not claim it worked), or "failed: <error>" without one. failed False: failed tools are left out.
        "" without results"""
        if not results:
            return ""
        lines = []
        for r in results.values():
            tool = r.get("tool", "unknown")
            if "error" in r and not failed:
                continue
            text = r.get("text") or (f"failed: {r['error']}" if "error" in r else "")
            lines.append(f"{tool}: {text}")

        return "\nTOOL_RESULTS\n" + "\n".join(lines) + "\n"
