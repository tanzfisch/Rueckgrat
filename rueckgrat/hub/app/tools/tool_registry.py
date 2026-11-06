import re
from typing import Dict, List, Optional, Any
from .tool import Tool
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
from .code_tool import RunCodeTool
from .write_file_tool import WriteFileTool

from app.common import get_logger, Utils, MessageQueue
logger = get_logger()

# #176 the order the tools of one message are asked for and run in. one tool is requested at a time, after the
# previous tool's result. a tuple shares one rank and is asked in the tuple's order. unlisted tools are last, in the
# order they were given. calls the model wrote for one tool keep that written order
TOOL_ORDER = [
    "current_time",     # the time and date other tools and the answer may build on
    "date_calc",        # date math, after the current date is known
    "search_memory",    # what the user told before, before any lookup or job that may need it
    ("wikipedia", "websearch", "fetch_url", "weather"),     # outside lookups, independent of each other
    "convert",          # converts the values the lookups found (e.g. a price in another currency)
    "calculate",        # computes with converted values, convert before calculate
    "run_code",         # the slowest and broadest check, after the quick lookups and math
    "write_file",       # files for the user, after the lookups they may quote, before the bubbles
    "show_map",         # bubbles under the answer: the map first
    "poll",             # then the poll
    "spawn_job",        # starts a background job after the reply's own tools, so its llm calls don't compete with theirs
    "remember",         # last: a new memory must not change this message's lookups
]
TOOL_RANK = {name: rank for rank, entry in enumerate(TOOL_ORDER) for name in ((entry,) if isinstance(entry, str) else entry)}


def _json_objects(text: str):
    """each {...} in text, with braces inside strings left alone"""
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
            break

class ToolRegistry:
    PROMPT_TOOLS = ["remember", "search_memory", "take_photo"]

    def __init__(self, db, infrastructure, task_queue):
        self.db = db
        self.infrastructure = infrastructure     
        self.task_queue = task_queue

        self.tools: Dict[str, type[Tool]] = {}
        self.parallel: Dict[str, bool] = {}  # tool name -> runs in parallel (True) or synchronous (False)
        self._register_tool(WebsearchTool)
        self._register_tool(ImageGenTool, parallel=True)
        self._register_tool(TakePhotoTool, parallel=True)
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
        self._register_tool(RunCodeTool)
        self._register_tool(WriteFileTool)

        temp = ", ".join(self.tools)
        logger.debug(f"registered tools: {temp}")

    def _register_tool(self, cls: type[Tool], parallel: bool = False):
        """parallel: the tool may run in parallel, default is synchronous execution"""
        self.tools[cls.name()] = cls
        self.parallel[cls.name()] = parallel

    @staticmethod
    def sort_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """a new list of the calls in TOOL_ORDER, stable: unlisted tools last, equal ranks keep their order"""
        return sorted(tool_calls, key=lambda call: TOOL_RANK.get(call.get("tool"), len(TOOL_ORDER)))

    @staticmethod
    def ordered_names(names: List[str]) -> List[str]:
        """unique names in TOOL_ORDER. a shared rank keeps the tuple's order, unlisted names stay last in input order"""
        unique = list(dict.fromkeys(names))

        def key(name: str):
            rank = TOOL_RANK.get(name, len(TOOL_ORDER))
            if rank < len(TOOL_ORDER):
                entry = TOOL_ORDER[rank]
                sub = entry.index(name) if isinstance(entry, tuple) else 0
            else:
                sub = unique.index(name)
            return (rank, sub)

        return sorted(unique, key=key)

    def tool_steps(self, tool_names: List[str], detected_tool_names: Optional[List[str]] = None) -> List[tuple]:
        """(name, required) in TOOL_ORDER. required means laya detected the tool (ToolDetectionTask). PROMPT_TOOLS and
        any other name laya did not detect stay optional: they are asked together once, after the required tools.
        unknown names are dropped"""
        detected = set(detected_tool_names or [])
        return [(name, name in detected and name not in self.PROMPT_TOOLS)
                for name in self.ordered_names(tool_names) if name in self.tools]

    @staticmethod
    def group_calls(tool_calls: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """the sorted calls in groups of one rank (e.g. the lookups, or two calculate calls).
        directing does not batch a rank: tool_steps asks for one tool at a time"""
        groups = []
        for call in ToolRegistry.sort_calls(tool_calls):
            if groups and TOOL_RANK.get(groups[-1][0].get("tool")) == TOOL_RANK.get(call.get("tool")):
                groups[-1].append(call)
            else:
                groups.append([call])
        return groups

    def execute(self, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_calls: List[Dict[str, Any]], parallel: bool = False) -> None:
        """runs the tool calls in TOOL_ORDER (sort_calls). synchronous tools (parallel=False) run one after another
        on this thread (task_queue.run), parallel tools are queued (task_queue.add) and run concurrently.
        parallel selects which tools run: None = all (default), False = only synchronous, True = only parallel"""
        for tool_call in self.sort_calls(tool_calls):
            tool_name = tool_call["tool"]
            if not tool_name in self.tools:
                logger.warning(f"unknown tool: {tool_name}")
                continue
            if parallel is not None and self.parallel[tool_name] != parallel:
                continue  # not selected in this call, the other execute() call runs it

            logger.debug(f"executing:\n{Utils.pretty_print(tool_call)}")

            ToolCls = self.tools[tool_name]
            tool_job = ToolCls(
                db=self.db,
                infrastructure=self.infrastructure,
                user_id=user_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                response=response,
                tool_call=tool_call
            )
            if self.parallel[tool_name]:
                self.task_queue.add(tool_job)
            else:
                self.task_queue.run(tool_job)

    def get_tools_prompt(self, skill_names: Optional[List[str]] = None) -> str:
        if not skill_names:
            selected = self.tools.values()
        else:
            selected = [self.tools[name] for name in skill_names if name in self.tools]

        result = ""
        for tool in selected:
            result += f"{tool.prompt()}"
        
        return result
    
    def get_tools_hydrated(self, tool_names: List[str], detected_tool_names: Optional[List[str]] = None) -> str:
        """tool directing prompt: the full prompt() of exactly these tools plus a strict JSON-only call rule.
        tool_names must not be empty (get_tools_prompt() would return all tools).
        laya-detected names (detected_tool_names, except PROMPT_TOOLS) must be called. every other tool stays optional"""
        tools = self.get_tools_prompt(tool_names)
        known = [name for name in tool_names if name in self.tools]
        required = [name for name in dict.fromkeys(detected_tool_names or []) if name in known and name not in self.PROMPT_TOOLS]
        prioritize = ("Prioritize tools over your own knowledge: whenever an available tool can handle part of the query, "
                      "call it for that part even if you are confident you already know the answer.")
        if len(required) == 1 and len(known) == 1:
            tools_intro = "Full instructions for the tool to call:"
            call_guidance = ("This tool was detected as necessary for this query. You must call it. Output its JSON line. Do not skip it.\n"
                             + prioritize)
        elif required:
            tools_intro = "Full instructions for the available tools:"
            call_guidance = (f"These tools were detected as necessary and must be called: {', '.join(required)}.\n"
                             "Output the JSON call for each of them. Do not skip them.")
            if len(required) < len(known):
                call_guidance += ("\nFor the other tools, call only those the query really needs. "
                                  "If none of them are needed, output nothing for them.")
            call_guidance += "\n" + prioritize
        else:
            # one combined request for every tool laya did not require. nothing is a valid answer
            return f"""TOOLS:

These tools are optional. Their full instructions:
{tools}

HOW TO CALL:
Call a tool only if the query really needs it. If the query needs none of them, output nothing. Outputting nothing is the correct answer when the query needs none of them.
If you do call a tool, write ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in.
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""
        return f"""TOOLS:

{tools_intro}
{tools}

HOW TO CALL:
Your answer MUST be the tool call as ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in.
{call_guidance}
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""

    def extract_tool_calls(self, text: str) -> tuple[List[Dict], str]:
        """json objects that name a registered tool. braces inside strings count, so a file can contain code"""
        tool_calls = []
        cleaned_text = text or ""
        for match in _json_objects(cleaned_text):
            if '"tool"' not in match:
                continue
            try:
                data = Utils.json_loads(match)
            except Exception as e:
                logger.error(f"failed to extract tool calls {repr(e)}")
                return None, None
            if data and data.get("tool") in self.tools:
                tool_calls.append(data)
                cleaned_text = cleaned_text.replace(match, "").strip()

        cleaned_text = re.sub(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', '', cleaned_text, flags=re.IGNORECASE).strip()
        cleaned_text = re.sub(r"```.*?```", "", cleaned_text, flags=re.DOTALL)
        cleaned_text = re.sub(r"`.*?`", "", cleaned_text)
        return tool_calls, cleaned_text