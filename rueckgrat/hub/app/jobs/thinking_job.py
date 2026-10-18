from .job_queue import Job
from typing import Dict, Any, List, Optional
import json
import random
from ..utils.prompt_compiler import PromptCompiler

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

# user instruction per phase. step 1 sees only the tool index, step 2 the full instructions of the requested tools
INDEX_INSTRUCTION = """
THINKING ONLY, step 1 of 2. No final response.
Does the query need one of the TOOLS?
- yes: output ONLY the request_tools JSON line, nothing else.
- no: quickly break down the query, note key context/needs and plan the answer structure, short analysis + plan only.
"""
HYDRATED_INSTRUCTION = """
THINKING ONLY, step 2 of 2. No final response.
Output ONLY the JSON tool call line(s) for the query, one per line, exactly in the format of HOW TO CALL. Nothing else: no words, no analysis.
"""

class ThinkingJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure, tool_registry, tool_names: Optional[List[str]] = None):
        super().__init__()
        self.tool_names = tool_names  # None: first call with the tool index. list: call with these tools' full prompts
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry

    def execute(self) -> None:
        self.thinking_response = self._thinking(self.request)

    def result(self) -> Dict[str, Any]:
        return self.thinking_response
      
    def _thinking(self, request: ChatRequest):
        try:
            contact = self.db.get_contact_by_id(request.contact_id)
            conversation = self.db.get_conversation(request.conversation_id)

            compiler = PromptCompiler(
                contact=contact, 
                conversation=conversation, 
                user_name=request.name, 
                thinking=True,
                tool_registry=self.tool_registry,
                tool_names=self.tool_names
            )

            system_prompt, context_prompt = compiler.build_prompt()
            messages = [{"role": "developer", "content": system_prompt}]
            if context_prompt:
                messages.append({"role": "developer", "content": context_prompt})
            
            instruction = INDEX_INSTRUCTION if self.tool_names is None else HYDRATED_INSTRUCTION
            query = f"""{instruction}
THE QUERY
{request.content}
"""            
            messages.append({"role": "user", "content": query})

            logger.debug(f"thinking prompt:\n{Utils.pretty_print(messages)}")

            response_content = self.infrastructure.chat(
                messages=messages,
                temperature=0.3,
                seed=random.randint(0, 100000)
            )

            # only the index call may request tools, a hydrated call can't loop
            tool_request = self.tool_registry.extract_tool_request(response_content) if self.tool_names is None else None
            tool_calls, content = self.tool_registry.extract_tool_calls(response_content)
            if self.tool_names is None and tool_request is None:
                # no request json: direct calls of index tools or a tool named in the text become a request,
                # step 2 then makes the calls with the full instructions
                tool_request = self.tool_registry.guess_tool_request(response_content, tool_calls)
                if tool_request:
                    tool_calls = []
            return {
                "content": content,
                "tool_calls": tool_calls,
                "tool_request": tool_request
            }            

        except Exception as e:
            logger.error(f"failed to think {repr(e)}")       

    