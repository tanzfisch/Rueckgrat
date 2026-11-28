import time
import traceback
import json
from .task_queue import Task
from typing import Dict, Any, List, Optional, Callable
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
                 message_id: int = None, excluded_tools: tuple = (), recommended_tools: List[str] = (),
                 detach: Optional[Callable[[], bool]] = None, tool_calls: Optional[List[Dict[str, Any]]] = None, history: int = 0):
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
        self.tool_calls = tool_calls
        self.history = history          # how many messages before this turn's the setup sees (_history)
        self.history_text: Optional[str] = None
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

    def get_executed(self) -> List[Dict[str, Any]]:
        """the calls that ran (or were recorded), in order: {"call", "ms"} each"""
        return list(self.executed)

    def get_tool_names(self) -> List[str]:
        """the mandatory tools of the last setup, after the prompt tools and the companions joined"""
        return list(self.tool_names or [])

    def get_recommended(self) -> List[str]:
        """the recommended tools of the last setup"""
        return list(self.recommended or [])

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

            requests = self._rounds(self.tool_names, self.recommended, self.request.content)
            if requests is not None:
                self._find_tools(requests)

            logger.debug(f"execution task results:\n{Utils.pretty_print(self.tool_response)}")

        except Exception as e:
            logger.error(f"failed to direct tools {repr(e)}\n{traceback.format_exc()}")

    def _rounds(self, mandatory: List[str], recommended: List[str], prompt_text: str, step: str = "",
                also: List[str] = ()) -> Optional[List[Dict[str, Any]]]:
        """the rounds of a tool setup (ToolRegistry.rounds), also: optional tools offered in the last round (no round of
        their own). returns the find_tools calls, None when one of the PRIORITY_TOOLS was called: nothing runs after it
        (ToolRegistry.ends_setup)"""
        ranked_groups = self.tool_registry.rounds(mandatory, recommended)
        if ranked_groups and also:
            ranked_groups[-1] += [name for name in also if name not in ranked_groups[-1]]
        requests: List[Dict[str, Any]] = []
        for round, tools in enumerate(ranked_groups, 1):
            label = f"{step}{round}/{len(ranked_groups)}"
            logger.debug(f"tool execution ({label}): {', '.join(tools)}"
                         + (f" (recommended: {', '.join(t for t in tools if t in recommended)})" if any(t in recommended for t in tools) else ""))
            tool_calls = self._round(label, tools, recommended, prompt_text)
            requests += [call for call in tool_calls if call.get("tool") == self.FIND_TOOLS]
            priority = self.tool_registry.ends_setup(tool_calls)
            if priority:
                logger.debug(f"{priority} was called, nothing runs after it")
                return None
        return requests

    def _find_tools(self, requests: List[Dict[str, Any]]) -> None:
        """the find_tools calls: a detection on their tasks, the tools it finds that were not offered yet get extra rounds
        (with find_tools again, at most FIND_TOOLS_STEPS in a row)"""
        from .tool_detection_task import ToolDetectionTask     # tool_detection_task imports the task package too
        step = 0
        while requests and step < self.FIND_TOOLS_STEPS:
            step += 1
            task = "; ".join(dict.fromkeys(filter(None, (self.tool_registry.tools[self.FIND_TOOLS].task(call) for call in requests))))
            if not task:
                break
            # no db or conversation: the task string is what to detect, not a chat turn (the conversation would
            # re-offer tools for the original message)
            detection = ToolDetectionTask(task, self.tool_registry, self.infrastructure, excluded_tools=self.excluded_tools)
            self.tool_registry.task_queue.run(detection)
            detection.trace(self.request.conversation_id, f"find_tools {step}/{self.FIND_TOOLS_STEPS}")
            # a tool offered already is not offered again: the poll would be asked twice
            detected = self._bands(detection.tool_names or [], detection.recommended or [])
            offered = set(self.tool_names + self.recommended)
            mandatory, recommended = ([name for name in band if name not in offered] for band in detected)
            found, detected = mandatory + recommended, detected[0] + detected[1]
            logger.info(f"find_tools {step}/{self.FIND_TOOLS_STEPS} ({detection.source() or 'nothing decided'}): {task[:200]} -> {detected or 'nothing'}, new: {found}")
            text = tool_prompts.FIND_TOOLS_FOUND_PART.format(task=task, tools=", ".join(found)) if found \
                else tool_prompts.FIND_TOOLS_OFFERED_PART.format(task=task, tools=", ".join(detected)) if detected \
                else tool_prompts.FIND_TOOLS_NONE_PART.format(task=task)
            self.tool_response[self.FIND_TOOLS] = {"tool": self.FIND_TOOLS, "text": text}
            if not found:
                break
            self.tool_names += [name for name in mandatory if name not in self.tool_names]
            self.recommended += [name for name in recommended if name not in self.recommended]
            again = [self.FIND_TOOLS] if step < self.FIND_TOOLS_STEPS and self.FIND_TOOLS not in self.excluded_tools else []
            requests = self._rounds(mandatory, recommended, self.request.content + tool_prompts.FIND_TOOLS_ROUND_PART.format(task=task),
                                    step=f"find {step} ", also=again)

    def _round(self, label: str, tools: List[str], recommended: List[str], prompt_text: str) -> List[Dict[str, Any]]:
        """one tool setup: one llm call writes the calls of tools (prompt_text: the task, with the earlier results), they run
        together and their results go into tool_response (a cut off reply: a note for the tools whose calls are missing).
        returns the calls that ran"""
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
        if tool_calls:
            self._run(tool_calls)
        self.tool_registry.merge_results(self.tool_response, cut_off)
        return tool_calls

    def _timezone(self):
        """the user's timezone for the setup prompt (clock.user_timezone), None without a user or db"""
        return user_timezone(self.db, self.get_user_id()) if self.db is not None and self.get_user_id() is not None else None

    def _call(self, call: Dict[str, Any]) -> Dict[str, Any]:
        """the call as the tool gets it: without background and llm_timeout, only an agent's worker sets them (Worker._run)"""
        return {key: value for key, value in call.items() if key not in ("background", "llm_timeout")}

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
    def results_prompt(results: Dict[str, Dict[str, Any]]) -> str:
        """the TOOL_RESULTS block of the results for a reply prompt. a failed tool keeps its text (what failed, so the
        reply does not claim it worked), or "failed: <error>" without one. "" without results"""
        if not results:
            return ""
        lines = []
        for r in results.values():
            tool = r.get("tool", "unknown")
            text = r.get("text") or (f"failed: {r['error']}" if "error" in r else "")
            lines.append(f"{tool}: {text}")

        return "\nTOOL_RESULTS\n" + "\n".join(lines) + "\n"
