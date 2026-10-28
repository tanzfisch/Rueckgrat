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
    PROMPT_TOOLS = ["remember", "search_memory", "take_photo"]

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
    
    def get_tools_hydrated(self, tool_names: List[str]) -> str:
        """tool directing prompt: the full prompt() of exactly these tools plus a strict JSON-only call rule.
        tool_names must not be empty (get_tools_prompt() would return all tools)"""
        tools = self.get_tools_prompt(tool_names)
        examples = "\n".join(self.tools[name].example() for name in tool_names if name in self.tools)
        return f"""TOOLS:

The query may need these tools. Their full instructions:
{tools}

HOW TO CALL:
Your answer MUST be the tool call as ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in.
Call only the tools the query really needs. If it needs none, output nothing.
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""

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
                except Exception as e:
                    logger.error(f"failed to extract tool calls {repr(e)}")
                    return None, None
                
            # remove json artifacts
            cleaned_text = re.sub(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', '', cleaned_text, flags=re.IGNORECASE).strip()
            cleaned_text = re.sub(r"```.*?```", "", cleaned_text, flags=re.DOTALL)
            cleaned_text = re.sub(r"`.*?`", "", cleaned_text)
            
            return tool_calls, cleaned_text