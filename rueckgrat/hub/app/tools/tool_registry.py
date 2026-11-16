import re
import json
import time
import threading
import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from typing import Dict, List, Optional, Any, Mapping, Union, Callable
from .tool import Tool
from . import prompts
from app.utils.trace import Trace
from .image_gen_tool import ImageGenTool
from .take_photo_tool import TakePhotoTool
from .websearch_tool import WebsearchTool
from .conversion_tool import ConversionTool
from .calculator_tool import CalculatorTool
from .current_time_tool import CurrentTimeTool
from .date_calc_tool import DateCalcTool
from .wikipedia_tool import WikipediaTool
from .weather_tool import WeatherTool
from .fetch_url_tool import FetchUrlTool
from .remember_tool import RememberTool
from .search_memory_tool import SearchMemoryTool
from .spawn_agent_job_tool import SpawnAgentJobTool
from .poll_tool import PollTool
from .map_tool import MapTool
from .price_finder_tool import PriceFinderTool
from .code_tool import RunCodeTool
from .bash_tool import BashTool
from .write_file_tool import WriteFileTool
from .share_file_tool import ShareFileTool
from .find_tools_tool import FindToolsTool

from app.common import get_logger, Utils, MessageQueue
logger = get_logger()

class ToolRegistry:
    # the order the tools are to be executed
    TOOL_ORDER = [
        ("spawn_job", "current_time"),
        "date_calc",
        ("search_memory", "find_tools", "wikipedia", "websearch", "fetch_url", "weather", "price_finder"),
        "convert",
        ("calculate", "run_code", "bash", "share_file"),    # share_file in bash's round: it runs after the calls that make the files
        ("show_map", "poll", "write_file", "generate_image", "take_photo", "remember"),
    ]

    TOOL_RANK = {name: rank for rank, entry in enumerate(TOOL_ORDER) for name in ((entry,) if isinstance(entry, str) else entry)}
    PROMPT_TOOLS = ["remember", "search_memory", "take_photo", "find_tools"]   # find_tools shares search_memory's round, no extra setup call
    FIX_TOOLS = ["run_code", "bash", "share_file", "write_file"]     # offered again in a worker's fix rounds (ToolExecutionTask), in this order
    RUN_TOOLS = ("run_code", "bash")    # a worker's mandatory one with no call is a problem for its fix rounds (not_called)
    PRIORITY_TOOL = "spawn_job"   # overrides all other tools
    WORKER_EXCLUDED_TOOLS = ("spawn_job", "remember", "poll", "show_map")
    DETACHED_TOOLS = ("show_map", "poll", "write_file", "generate_image", "take_photo", "remember")
    REPLY_TOOLS = ("remember", "take_photo")    # a chat reply calls these itself at its end (MetaTask), not the tool setup
    REPLY_CALL = re.compile(r'(?:^|\n)[ \t]*(?:```(?:json)?\s*)?\{\s*"tool"')   # where the calls at the end of a reply start
    PROJECT_QUESTIONS = [
        "Does the user report a bug in a program, like a crash, an error or wrong behaviour?",
        "Does the user ask for a fix or a change to a program, an app or a game that was made earlier?",
    ]
    PROJECT_TOOLS = ("spawn_job", "bash", "write_file")

    def __init__(self, db, infrastructure, task_queue):
        self.db = db
        self.infrastructure = infrastructure     
        self.task_queue = task_queue

        self._registered: Dict[str, type[Tool]] = {}    # every tool, self.tools the ones that can be used now
        self._register_tool(WebsearchTool)
        self._register_tool(ImageGenTool)
        self._register_tool(TakePhotoTool)
        self._register_tool(ConversionTool)
        self._register_tool(CalculatorTool)
        self._register_tool(CurrentTimeTool)
        self._register_tool(DateCalcTool)
        self._register_tool(WikipediaTool)
        self._register_tool(WeatherTool)
        self._register_tool(FetchUrlTool)
        self._register_tool(RememberTool)
        self._register_tool(SearchMemoryTool)
        self._register_tool(SpawnAgentJobTool)
        self._register_tool(PollTool)
        self._register_tool(MapTool)
        self._register_tool(PriceFinderTool)
        self._register_tool(RunCodeTool)
        self._register_tool(BashTool)
        self._register_tool(WriteFileTool)
        self._register_tool(ShareFileTool)
        self._register_tool(FindToolsTool)

        temp = ", ".join(self._registered)
        logger.debug(f"registered tools: {temp}")

    def _register_tool(self, cls: type[Tool]):
        self._registered[cls.name()] = cls

    @property
    def tools(self) -> Dict[str, type[Tool]]:
        """the registered tools that can be used now: every capability a tool needs (Tool.requires) is available. the others
        are not detected, offered, listed or run, e.g. no image generation: no generate_image and take_photo"""
        return {name: tool for name, tool in self._registered.items() if self.usable(tool)}

    def usable(self, tool: type[Tool]) -> bool:
        """the capabilities tool needs are available now (Infrastructure.available)"""
        return not tool.requires or self.infrastructure is None or all(self.infrastructure.available(name) for name in tool.requires)

    def attach_held(self, db, user_id: int, conversation_id: int, message_id: int, attachments: List[Dict[str, Any]], push: bool = True) -> None:
        """attaches the files tools held without a message (their results' "attachments", each names its tool) to message_id,
        by that tool's attach_held. push: the user has an open /ws. a file that fails is logged and skipped"""
        for held in attachments or []:
            try:
                self._registered[held["tool"]].attach_held(db, user_id, conversation_id, message_id, held, push)
                Trace.write(conversation_id, "held attachment attached", name=held.get("name"), tool=held.get("tool"), message_id=message_id)
            except Exception as e:
                logger.error(f"held attachment {held.get('name')} of {held.get('tool')} not attached {repr(e)}")
                Trace.write(conversation_id, "held attachment NOT attached", name=held.get("name"), tool=held.get("tool"), error=repr(e))

    def prioritized(self, tool_names: List[str]) -> List[str]:
        """only the PRIORITY_TOOL when it is among tool_names, else tool_names"""
        return [self.PRIORITY_TOOL] if self.PRIORITY_TOOL in (tool_names or []) else list(tool_names or [])

    def bands(self, mandatory: List[str], recommended: List[str]) -> tuple[List[str], List[str]]:
        """(mandatory, recommended) of a detection: a mandatory PRIORITY_TOOL is the only tool, a tool in both is mandatory"""
        mandatory = self.prioritized(mandatory)
        if self.PRIORITY_TOOL in mandatory:
            return mandatory, []
        return mandatory, [name for name in dict.fromkeys(recommended or []) if name not in mandatory]

    def rounds(self, tool_names: List[str], recommended: List[str] = ()) -> List[List[str]]:
        """the rounds of a tool setup (ranked_groups of all tools). a recommended PRIORITY_TOOL is a round on its own: the first
        when no other tool was detected as mandatory (the PROMPT_TOOLS always are), else the last, so an uncertain one does
        not take over from a sure tool. ToolExecutionTask stops after it when it was called"""
        names = list(dict.fromkeys(list(tool_names or []) + list(recommended or [])))
        if self.PRIORITY_TOOL in (recommended or []) and self.PRIORITY_TOOL not in (tool_names or []):
            rest = self.ranked_groups([name for name in names if name != self.PRIORITY_TOOL])
            if any(name not in self.PROMPT_TOOLS for name in tool_names or []):
                return rest + [[self.PRIORITY_TOOL]]
            return [[self.PRIORITY_TOOL]] + rest
        return self.ranked_groups(names)

    def available(self, tool_names: List[str], excluded: tuple = ()) -> List[str]:
        """the names of tool_names that can be used now (tools) without the excluded ones, in their order, no duplicates"""
        tools = self.tools
        return [name for name in dict.fromkeys(tool_names or []) if name in tools and name not in excluded]

    def companions(self, tool_names: List[str], excluded: tuple = ()) -> List[str]:
        """the tools offered with one of tool_names (Tool.offered_with) that are not among them or excluded"""
        return [name for name, tool in self.tools.items() if set(tool.offered_with) & set(tool_names or [])
                and name not in (tool_names or []) and name not in excluded]

    def optional(self, name: str) -> bool:
        """the model decides on its own whether to call it: the PROMPT_TOOLS and the companions (Tool.offered_with)"""
        return name in self.PROMPT_TOOLS or bool(getattr(self.tools.get(name), "offered_with", ()))

    def project_tools(self, excluded: tuple = ()) -> List[str]:
        """the PROJECT_TOOLS a fix or change of an existing project selects, without the excluded ones"""
        return self.available(list(self.PROJECT_TOOLS), excluded)

    @classmethod
    def ordered_names(cls, names: List[str]) -> List[str]:
        """unique names in TOOL_ORDER. a shared rank keeps the tuple's order, unlisted names stay last in input order"""
        unique = list(dict.fromkeys(names))

        def key(name: str):
            rank = cls.TOOL_RANK.get(name, len(cls.TOOL_ORDER))
            if rank < len(cls.TOOL_ORDER):
                entry = cls.TOOL_ORDER[rank]
                sub = entry.index(name) if isinstance(entry, tuple) else 0
            else:
                sub = unique.index(name)
            return (rank, sub)

        return sorted(unique, key=key)

    def ranked_groups(self, tool_names: List[str]) -> List[List[str]]:
        tools = self.tools
        names = [name for name in self.ordered_names(tool_names or []) if name in tools]
        if names and all(name in self.PROMPT_TOOLS for name in names):
            return [names]
        ranked_groups = []
        for name in names:
            rank = self.TOOL_RANK.get(name)
            if ranked_groups and rank is not None and self.TOOL_RANK.get(ranked_groups[-1][0]) == rank:
                ranked_groups[-1].append(name)
            else:
                ranked_groups.append([name])
        return ranked_groups

    def _tool_job(self, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any],
                  message_id: Optional[int] = None) -> Optional[Tool]:
        tool_name = tool_call.get("tool")
        tool = self.tools.get(tool_name)
        if tool is None:
            logger.error(f"unknown or not available tool: {tool_name}")
            return None

        logger.debug(f"executing:\n{Utils.pretty_print(tool_call)}")
        tool_job = tool(
            db=self.db,
            infrastructure=self.infrastructure,
            user_id=user_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            tool_call=tool_call
        )
        tool_job.message_id = message_id
        return tool_job

    def _run_job(self, tool_job: Tool) -> Optional[Dict[str, Any]]:
        started = time.monotonic()
        if not self.task_queue.run(tool_job):
            logger.error(f"tool failed: {tool_job.name()}")
            Trace.write(tool_job.conversation_id, f"tool {tool_job.name()} failed", call=tool_job.tool_call)
            return None
        result = tool_job.get_result()
        if Trace.enabled():     # the call as the llm wrote it and the whole result text the next steps get
            own = (result or {}).get(tool_job.name()) or {}
            others = {k: v for k, v in own.items() if k not in ("tool", "text")} if isinstance(own, dict) else {}
            Trace.write(tool_job.conversation_id, f"tool {tool_job.name()}",
                        f"CALL:\n{json.dumps(tool_job.tool_call, ensure_ascii=False, indent=1, default=str)}\nRESULT:\n"
                        f"{own.get('text', '') if isinstance(own, dict) else own}",
                        seconds=f"{time.monotonic() - started:.2f}", message_id=tool_job.message_id, result=others or None)
        return result

    def execute(self, user_id: int, contact_id: int, conversation_id: int,
                  tool_calls: Union[Dict[str, Any], List[Dict[str, Any]]],
                  message_id: Optional[int] = None, excluded: tuple = (),
                  detach: Optional[Callable[[], bool]] = None) -> Optional[Dict[str, Any]]:
        """runs one tool call, or a list of them in parallel, and returns once all are done.
        the results are merged in the order of the calls ({tool name: result}), None if no call returned a result.
        message_id: the assistant message the calls are for. a call of an excluded tool is dropped, also when the llm
        wrote it without being offered the tool.
        detach: given, a call of a DETACHED_TOOLS tool for a stored message is started in the background and not waited for,
        its planned_result is returned instead. detach() is called once before: False (the turn is gone) drops those calls.
        the calls run on their own threads, not on the task queue's workers: the caller waits for them,
        so they cannot block each other or the caller for a free worker"""
        if isinstance(tool_calls, dict):
            tool_calls = [tool_calls]
        for call in tool_calls:
            if call.get("tool") in excluded:
                logger.warning(f"excluded tool dropped: {call.get('tool')}")
        tool_calls = [call for call in tool_calls if call.get("tool") not in excluded]

        jobs = [job for job in (self._tool_job(user_id, contact_id, conversation_id, call, message_id) for call in tool_calls) if job]
        detached = [job for job in jobs if detach and self.detachable(job)]
        if detached and not detach():
            logger.info(f"turn gone, detached calls dropped: {[job.name() for job in detached]}")
            jobs = [job for job in jobs if job not in detached]
            detached = []
        waited = [job for job in jobs if job not in detached]
        if not jobs:
            return None

        for job in detached:
            self._start_detached(job)

        # one lane per call, the calls of the sequential tools share one lane in their order: they work on the same files
        lanes = [[job] for job in waited if not job.sequential] + ([in_order] if (in_order := [job for job in waited if job.sequential]) else [])
        if len(lanes) == 1:
            done = self._run_lane(lanes[0])
        elif lanes:
            # copy_context: the status messages of each tool go to the caller's user (MessageQueue.user_scope)
            with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
                futures = [pool.submit(contextvars.copy_context().run, self._run_lane, lane) for lane in lanes]
                done = {key: result for future in futures for key, result in future.result().items()}
        else:
            done = {}

        merged: Dict[str, Any] = {}
        for job in jobs:
            self.merge_results(merged, job.planned_result() if job in detached else done[id(job)])
        return merged or None

    def _run_lane(self, jobs: List[Tool]) -> Dict[int, Optional[Dict[str, Any]]]:
        """runs the jobs one after another inside their tools' sharing() (the bash calls: one sandbox): {id(job): its result}"""
        with ExitStack() as stack:
            for tool in dict.fromkeys(type(job) for job in jobs):
                stack.enter_context(tool.sharing())
            return {id(job): self._run_job(job) for job in jobs}

    GROUND_WORD = re.compile(r"[^\W_]{3,}|\d+(?:[.,]\d+)?")    # the words and numbers grounded() compares

    def grounded(self, call: Dict[str, Any], text: str) -> bool:
        """whether a call takes at least one of its values from text (the message and the earlier results). a recommended
        call that shares nothing with it was made up, like the tool's prompt example ("100 USD to EUR" in a fractal task)"""
        words = {word.lower() for word in self.GROUND_WORD.findall(text or "")}
        values = [value for key, value in call.items() if key != "tool"]
        # a value written in the message as it is counts too: "ls -la ~" has no word of 3 letters
        if any(isinstance(value, str) and value.strip() and value.strip().lower() in (text or "").lower() for value in values):
            return True
        values = json.dumps(values, ensure_ascii=False, default=str)
        return any(word.lower() in words for word in self.GROUND_WORD.findall(values))

    def cut_off_result(self, text: str, tools: List[str], length: bool = False) -> Optional[Dict[str, Any]]:
        """{tool name: note} when the last call of a setup reply was cut off (the reply ran out of tokens) and is one of
        tools, None when every call is complete. the note tells the later rounds and the reply that it did not run.
        length: the llm said the reply hit max_new_tokens (finish_reason "length"), also after a complete last call
        the calls it did not write are missing: a note for the tool of the last call"""
        text = text or ""
        end = 0
        for found in self._json_objects(text):
            end = text.index(found, end) + len(found)
        match = re.search(r'\{\s*"tool"\s*:\s*"([^"]+)"', text[end:])
        if match and match.group(1) in tools:
            name = match.group(1)
            return {name: {"tool": name, "text": prompts.TOOL_CUT_OFF_PART.format(name=name)}}
        if length and tools:
            names = [name for name in re.findall(r'"tool"\s*:\s*"([^"]+)"', text) if name in tools]
            name = names[-1] if names else tools[0]
            return {name: {"tool": name, "text": prompts.TOOL_LENGTH_PART.format(name=name)}}
        return None

    def not_called(self, mandatory: List[str], calls: List[Dict[str, Any]]) -> List[str]:
        """the problems of the mandatory RUN_TOOLS that got no call (a tester that only listed the files)"""
        called = {call.get("tool") for call in calls}
        return [prompts.TOOL_NOT_CALLED_PART.format(name=name) for name in mandatory if name in self.RUN_TOOLS and name not in called]

    def problems(self, results: Optional[Mapping[str, Any]]) -> List[str]:
        """what went wrong in {tool name: result} that a fix round could repair (each tool's problems())"""
        return [problem for name, result in (results or {}).items() if isinstance(result, dict)
                for problem in self._registered.get(name, Tool).problems(result)]

    def detachable(self, tool_job: Tool) -> bool:
        return tool_job.name() in self.DETACHED_TOOLS and tool_job.has_message() and tool_job.runs_detached()

    def _start_detached(self, tool_job: Tool) -> None:
        """runs the call on its own thread for the caller's user, without status messages: the reply's status ends first"""
        def run():
            with MessageQueue.quiet_scope():
                self._run_job(tool_job)
        logger.debug(f"detached: {tool_job.name()} for message {tool_job.message_id}")
        threading.Thread(target=contextvars.copy_context().run, args=(run,), name=f"detached-{tool_job.name()}", daemon=True).start()

    def get_tools_prompt(self, skill_names: Optional[List[str]] = None, scope: Optional[Dict[str, int]] = None) -> str:
        """the instructions of the tools. scope: {user_id, contact_id, conversation_id} of the setup, the tools' prompt_for"""
        tools = self.tools
        if not skill_names:
            selected = tools.values()
        else:
            selected = [tools[name] for name in skill_names if name in tools]

        result = ""
        for tool in selected:
            result += f"{tool.prompt_for(**scope) if scope else tool.prompt()}"
        
        return result

    def merge_results(self, target: Dict[str, Any], result: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """merges {tool name: result} into target (changed and returned). a second result of the same tool
        is combined by that tool's merge() (tools: name -> tool class), Tool.merge when the tool is unknown"""
        for name, value in (result or {}).items():
            known = target.get(name)
            if not isinstance(known, dict) or not isinstance(value, dict):
                target[name] = value
                continue
            tool = self._registered.get(name, Tool)
            target[name] = tool.merge(known, value)
        return target    

    def split_tools(self, tool_names: List[str], recommended: List[str] = ()) -> tuple[List[str], List[str], List[str]]:
        """(mandatory, recommended, optional): PROMPT_TOOLS and companions are optional (optional()), the recommended ones
        the detection was not sure about, every other tool was detected and must be called"""
        names = list(tool_names or [])
        return ([name for name in names if not self.optional(name) and name not in recommended],
                [name for name in names if name in recommended and not self.optional(name)],
                [name for name in names if self.optional(name)])

    def get_tools_hydrated(self, tool_names: List[str], kind: str = "mandatory", scope: Optional[Dict[str, int]] = None) -> str:
        """the tools' instructions and how to call them. kind: "mandatory" (must be called), "recommended" (detected, but
        the model decides) or "optional" (PROMPT_TOOLS and companions, the model decides on its own). scope: see get_tools_prompt"""
        tools = self.get_tools_prompt(tool_names, scope)

        if kind == "recommended":
            return prompts.TOOLS_RECOMMENDED_PART.format(tools=tools)

        if kind == "reply":
            return prompts.TOOLS_REPLY_PART.format(tools=tools)

        if kind == "optional":
            return prompts.TOOLS_OPTIONAL_PART.format(tools=tools)

        return prompts.TOOLS_MANDATORY_PART.format(tools=tools)
    
    def reply_tools_prompt(self) -> str:
        """the REPLY_TOOLS that can be used now for the chat's system prompt, "" when none can"""
        names = self.available(list(self.REPLY_TOOLS))
        return self.get_tools_hydrated(names, kind="reply") if names else ""

    def split_reply(self, text: str, final: bool = True) -> tuple[str, List[Dict]]:
        """(the text for the user, the REPLY_TOOLS calls) of a chat reply, the calls are the json lines at its end.
        final False (still streaming): a last line that may become a call is held back. the text only grows while
        streaming, so the part sent already stays its start"""
        text = text or ""
        match = self.REPLY_CALL.search(text)
        if match and not final:
            return text[:match.start()].rstrip(), []    # the calls may still be cut off
        if match:
            calls, _ = self.extract_tool_calls(text[match.start():])
            return text[:match.start()].rstrip(), [call for call in calls or [] if call.get("tool") in self.REPLY_TOOLS]
        if not final:
            start = text.rfind("\n") + 1
            if text[start:].lstrip()[:1] in ("{", "`"):
                text = text[:start]
        return text.rstrip(), []

    def _json_objects(self, text: str):
        """yields each top level json from given text"""
        i, n = 0, len(text or "")
        while i < n:
            if text[i] != "{":
                i += 1
                continue
            depth, in_str, esc, start = 0, False, False, i
            for j in range(i, n):
                char = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif char == "\\":
                        esc = True
                    elif char == '"':
                        in_str = False
                    continue
                if char == '"':
                    in_str = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        yield text[start:j + 1]
                        i = j + 1
                        break
            else:
                logger.warning(f"tool call cut off, dropped: {text[start:start + 200]}")
                break

    def extract_tool_calls(self, text: str) -> tuple[List[Dict], str]:
        """json objects that name a registered tool. braces inside strings count, so a file can contain code"""
        tool_calls = []
        cleaned_text = text or ""
        tools = self.tools
        for match in self._json_objects(cleaned_text):
            if '"tool"' not in match:
                continue
            try:
                data = Utils.json_loads(match)
            except Exception as e:
                logger.error(f"failed to extract tool calls {repr(e)}")
                return None, None
            if data and data.get("tool") in tools:
                tool_calls.append(data)
                cleaned_text = cleaned_text.replace(match, "").strip()

        cleaned_text = re.sub(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', '', cleaned_text, flags=re.IGNORECASE).strip()
        cleaned_text = re.sub(r"```.*?```", "", cleaned_text, flags=re.DOTALL)
        cleaned_text = re.sub(r"`.*?`", "", cleaned_text)
        return tool_calls, cleaned_text