import re
from typing import Dict, List, Optional, Any
from .tool import Tool
from .image_gen_tool import ImageGenTool
from .take_photo_tool import TakePhotoTool
from .websearch_tool import WebsearchTool
from app.utils.message_queue import MessageQueue

from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class ToolRegistry:
    def __init__(self, db, infrastructure, job_queue):
        self.db = db
        self.infrastructure = infrastructure     
        self.job_queue = job_queue

        self.tools: Dict[str, type[Tool]] = {}
        self._register_tool(WebsearchTool)  
        self._register_tool(ImageGenTool)
        self._register_tool(TakePhotoTool)

    def _register_tool(self, cls: type[Tool]):
        self.tools[cls.name()] = cls
        logger.debug(f"registered tool: {cls.name()}")

    def execute(self, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]) -> None:
        tool_name = tool_call["tool"]
        if not tool_name in self.tools:
            logger.warning(f"unknown tool: {tool_name}")
            return None
                
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
            
            return tool_calls, cleaned_text