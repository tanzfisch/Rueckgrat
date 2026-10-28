from .job_queue import Job
from typing import Dict, Any, List
import json
import random
from ..utils.prompt_compiler import PromptCompiler

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

# the tools are detected before (ToolDetectionJob), the model only writes their calls
INSTRUCTION = """
THINKING ONLY. No final response.
Output ONLY the JSON tool call line(s) for the query, one per line, exactly in the format of HOW TO CALL. Nothing else: no words, no analysis.
"""

class ToolDirectingJob(Job):
    """turns the tools detected by ToolDetectionJob into executable calls: the model writes their arguments"""
    def __init__(self, request: ChatRequest, db, infrastructure, tool_registry, tool_names: List[str]):
        super().__init__()
        self.tool_names = tool_names  # the tools to call, the prompt gets their full instructions
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry

    def execute(self) -> None:
        self.tool_response = self._direct_tools(self.request)

    def result(self) -> Dict[str, Any]:
        return self.tool_response
      
    def _direct_tools(self, request: ChatRequest):
        try:
            contact = self.db.get_contact_by_id(request.contact_id)
            conversation = self.db.get_conversation(request.conversation_id)

            compiler = PromptCompiler(
                contact=contact,
                conversation=conversation,
                user_role_name=request.name,
                thinking=True,
                tool_registry=self.tool_registry,
                tool_names=self.tool_names
            )

            system_prompt, context_prompt = compiler.build_prompt()
            messages = [{"role": "developer", "content": system_prompt}]
            if context_prompt:
                messages.append({"role": "developer", "content": context_prompt})
            
            query = f"""{INSTRUCTION}
THE QUERY
{request.content}
"""            
            messages.append({"role": "user", "content": query})
            #logger.debug(f"tool directing prompt:\n{Utils.pretty_print(messages)}")

            response_content = self.infrastructure.chat(
                messages=messages,
                temperature=0.3,
                seed=random.randint(0, 100000)
            )

            tool_calls, content = self.tool_registry.extract_tool_calls(response_content)
            return {
                "content": content,
                "tool_calls": tool_calls
            }            

        except Exception as e:
            logger.error(f"failed to direct tools {repr(e)}")       

    