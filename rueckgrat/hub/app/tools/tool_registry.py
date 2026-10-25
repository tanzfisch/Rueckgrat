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

from app.common import get_logger, Utils, MessageQueue
logger = get_logger()

class ToolRegistry:
    REQUEST_TOOLS = "request_tools"     # meta tool: the model asks for the full instructions of some tools
    MAX_REQUESTED_TOOLS = 4

    def __init__(self, db, infrastructure, job_queue):
        self.db = db
        self.infrastructure = infrastructure     
        self.job_queue = job_queue

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

        temp = ", ".join(self.tools)
        logger.debug(f"registered tools: {temp}")

    def _register_tool(self, cls: type[Tool], parallel: bool = False):
        """parallel: the tool may run in parallel, default is synchronous execution"""
        self.tools[cls.name()] = cls
        self.parallel[cls.name()] = parallel

    def tools_by_category(self) -> Dict[str, List[str]]:
        """read only: {category: [tool names]} in registration order"""
        result: Dict[str, List[str]] = {}
        for name, cls in self.tools.items():
            result.setdefault(cls.category, []).append(name)
        return result

    def execute(self, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_calls: List[Dict[str, Any]], parallel: bool = False) -> None:
        """runs the tool calls in list order. synchronous tools (parallel=False) run one after another
        on this thread (job_queue.run), parallel tools are queued (job_queue.add) and run concurrently.
        parallel selects which tools run: None = all (default), False = only synchronous, True = only parallel"""
        for tool_call in tool_calls:
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
                self.job_queue.add(tool_job)
            else:
                self.job_queue.run(tool_job)

    def get_tools_prompt(self, skill_names: Optional[List[str]] = None) -> str:
        if not skill_names:
            selected = self.tools.values()
        else:
            selected = [self.tools[name] for name in skill_names if name in self.tools]

        result = ""
        for tool in selected:
            result += f"{tool.prompt()}"
        
        return result
    
    def get_tools_index(self) -> str:
        """step 1 prompt: one line per tool (name, category, description) plus the request procedure.
        the json examples are single lines so the extract regex matches them reliably"""
        lines = []
        for category, names in self.tools_by_category().items():
            for name in names:
                lines.append(f"- {name} ({category}): {self.tools[name].get_description()}")
        index = "\n".join(lines)
        return f"""TOOLS (step 1 of 2):

These tools exist, but here you only see their names. You can NOT call them directly yet.

{index}

HOW TO USE TOOLS:
Step 1, now: if the query needs one or more of these tools, output ONLY this one line of JSON with their names (max {self.MAX_REQUESTED_TOOLS}), nothing else:
{{"tool": "{self.REQUEST_TOOLS}", "names": ["tool_name"]}}
Step 2, next: you then get the full instructions of these tools and make the actual tool call.
If no tool is needed, output no JSON at all.

EXAMPLES:
"What time is it in Tokyo?" -> {{"tool": "{self.REQUEST_TOOLS}", "names": ["current_time"]}}
"How much is 20 % of 150 dollars in euros?" -> {{"tool": "{self.REQUEST_TOOLS}", "names": ["calculate", "convert"]}}
"Summarize this: https://example.com/news/article" -> {{"tool": "{self.REQUEST_TOOLS}", "names": ["fetch_url"]}}
"How are you today?" -> no JSON, no tool needed
"""

    def get_tools_hydrated(self, tool_names: List[str]) -> str:
        """step 2 prompt: the full prompt() of exactly these tools plus a strict JSON-only call rule.
        tool_names must not be empty (get_tools_prompt() would return all tools)"""
        tools = self.get_tools_prompt(tool_names)
        examples = "\n".join(self.tools[name].example() for name in tool_names if name in self.tools)
        return f"""TOOLS (step 2 of 2):

You requested these tools. Their full instructions:
{tools}

HOW TO CALL:
Your answer MUST be the tool call as ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in.
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""

    def extract_tool_request(self, text: str) -> Optional[Dict[str, List[str]]]:
        """finds a request_tools call in the model output. None if there is none,
        else {"names": [known tool names, max MAX_REQUESTED_TOOLS], "unknown": [ignored names]}.
        "names" may be a json list or a comma separated string"""
        json_pattern = r'\{[^{}]*"tool"\s*:\s*"' + self.REQUEST_TOOLS + r'"[^{}]*\}'
        matches = re.findall(json_pattern, text or "", re.DOTALL)
        if not matches:
            return None

        requested = []
        for match in matches:
            data = Utils.json_loads(match) or {}
            names = data.get("names", [])
            if isinstance(names, str):
                names = names.split(",")
            if isinstance(names, list):
                requested += [str(n).strip() for n in names if str(n).strip()]

        known, unknown = [], []
        for name in requested:
            if name in self.tools:
                if name not in known:
                    known.append(name)
            elif name not in unknown:
                unknown.append(name)
        if unknown:
            logger.warning(f"request_tools: ignoring unknown tools {unknown}")
        if len(known) > self.MAX_REQUESTED_TOOLS:
            logger.warning(f"request_tools: {len(known)} tools requested, keeping the first {self.MAX_REQUESTED_TOOLS}")
            known = known[:self.MAX_REQUESTED_TOOLS]
        return {"names": known, "unknown": unknown}

    def guess_tool_request(self, text: str, tool_calls: List[Dict]) -> Optional[Dict[str, List[str]]]:
        """step 1 fallback when the model did not write a request_tools json:
        - it called index tools directly -> request exactly those tools
        - it only talked about a tool ('use the "current_time" tool ... let me request the tool instructions')
          -> request the tool names it wrote in quotes or backticks, if it also wrote the word "tool"
        returns the same shape as extract_tool_request() or None"""
        names = [call["tool"] for call in tool_calls if call.get("tool") in self.tools]
        if not names and re.search(r"\btools?\b", text or "", re.IGNORECASE):
            names = [name for name in self.tools if re.search(rf"[\"'`]{re.escape(name)}[\"'`]", text)]
        names = list(dict.fromkeys(names))[:self.MAX_REQUESTED_TOOLS]
        if not names:
            return None
        logger.warning(f"request_tools: no request json, treating it as a request for {names}")
        return {"names": names, "unknown": []}

    def extract_tool_calls(self, text: str) -> tuple[List[Dict], str]:
            tool_calls = []
            cleaned_text = text

            json_pattern = r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}'
            matches = re.findall(json_pattern, text, re.DOTALL)
            
            for match in matches:
                try:
                    data = Utils.json_loads(match)
                    if data and "tool" in data:
                        if data["tool"] in self.tools:
                            tool_calls.append(data)
                            cleaned_text = cleaned_text.replace(match, "").strip()
                        elif data["tool"] == self.REQUEST_TOOLS:
                            # handled by extract_tool_request, only remove it from the text
                            cleaned_text = cleaned_text.replace(match, "").strip()
                except Exception as e:
                    logger.error(f"failed to extract tool calls {repr(e)}")
                    return None, None
                
            # remove json artifacts
            cleaned_text = re.sub(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', '', cleaned_text, flags=re.IGNORECASE).strip()
            cleaned_text = re.sub(r"```.*?```", "", cleaned_text, flags=re.DOTALL)
            cleaned_text = re.sub(r"`.*?`", "", cleaned_text)
            
            return tool_calls, cleaned_text