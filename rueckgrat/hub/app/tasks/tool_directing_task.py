from .task_queue import Task
from typing import Dict, Any, List, Optional
import random
from ..utils.prompt_compiler import PromptCompiler

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

# a laya-detected tool is asked for on its own. the other tools share one later request and may all be skipped
INSTRUCTION = """
THINKING ONLY. No final response.
If you call a tool, output ONLY its JSON tool call line(s), one per line, exactly in the format of HOW TO CALL. Nothing else: no words, no analysis.
"""
OPTIONAL_INSTRUCTION = """
THINKING ONLY. No final response.
These tools are optional. If the query needs none of them, output nothing. Outputting nothing is the correct answer when the query needs none of them.
If you do call a tool, output ONLY its JSON tool call line(s), one per line, exactly in the format of HOW TO CALL. Nothing else: no words, no analysis.
"""

# results of the tools that already ran, carried into the next mandatory tool's request
RESULTS_SO_FAR = """
RESULTS SO FAR (of the tools that already ran for this query):
{results}
Use these results for values this call depends on.
"""
# the same results for the optional request: they do not require a call
OPTIONAL_RESULTS = """
RESULTS SO FAR (of the tools that already ran for this query):
{results}
If you do call a tool, take a value that depends on these results from them.
"""
# remember and spawn_job are about what the user said. later tool results must not rewrite them
# (spawn_job: the job does its own research, and when laya detects it the other detected tools are dropped)
KEEP_CALL = """
Write this call from the query itself. Results of other tools must not change it.
"""
KEEP_CALLS = ("remember", "spawn_job")

def directing_query(query: str, tool_names: List[str], results: str = "", required: bool = False) -> str:
    """the user message for one directing call. a required keep-call (spawn_job) ignores earlier results.
    an optional request, including remember, does not: it may output nothing and is not told to write a call"""
    keep = required and len(tool_names) == 1 and tool_names[0] in KEEP_CALLS
    parts = [(INSTRUCTION if required else OPTIONAL_INSTRUCTION).strip()]
    if keep:
        parts.append(KEEP_CALL.strip())
    elif results and results.strip():
        template = RESULTS_SO_FAR if required else OPTIONAL_RESULTS
        parts.append(template.format(results=results.strip()).strip())
    parts.append(f"THE QUERY\n{query}")
    return "\n\n".join(parts) + "\n"

def run_tool_sequence(steps, direct, execute, results_text, on_failure, is_parallel, interrupted=None, direct_optional=None):
    """laya-detected tools are asked one at a time, in steps order, and a synchronous tool runs before the next ask.
    every other tool is then one combined request (direct_optional). an empty answer calls nothing and is not a failure.
    direct(name, required, results) -> {"tool_calls", "content"} or None when that directing call failed.
    direct_optional(names, results) -> the same, for the optional tools together. required when steps has an optional tool.
    execute(calls) runs those calls and returns only after their results are available.
    results_text() -> results so far. a required KEEP_CALL is asked without them.
    on_failure(name, error) records a mandatory tool that produced no call.
    is_parallel(name) -> the call is returned for later (images attach to the reply message) and is not executed here.
    interrupted() -> stop before the next request.
    returns (sync_calls, parallel_calls, was_interrupted). the caller finalizes only after this returns,
    and skips finalization when was_interrupted is true"""
    if interrupted is None:
        interrupted = lambda: False
    from app.tools.tool_registry import ToolRegistry
    sync, parallel = [], []
    mandatory = [(name, True) for name, required in steps if required]
    optional = [name for name, required in steps if not required]

    def consume(calls):
        ordered = ToolRegistry.sort_calls(calls)
        sync_calls = [call for call in ordered if not is_parallel(call.get("tool"))]
        parallel.extend(call for call in ordered if is_parallel(call.get("tool")))
        if sync_calls:
            execute(sync_calls)
            sync.extend(sync_calls)

    for name, required in mandatory:
        if interrupted():
            return sync, parallel, True
        results = "" if name in KEEP_CALLS else (results_text() or "")
        directed = direct(name, required, results)
        calls = [call for call in (directed.get("tool_calls") or []) if call.get("tool") == name] if directed else []
        if not calls:
            on_failure(name, "tool directing failed" if not directed else "no call written")
            continue
        consume(calls)
    if interrupted():
        return sync, parallel, True
    if optional:
        if direct_optional is None:
            raise TypeError("direct_optional is required when the sequence has optional tools")
        directed = direct_optional(optional, results_text() or "")
        allowed = set(optional)
        calls = [call for call in (directed.get("tool_calls") or []) if call.get("tool") in allowed] if directed else []
        if calls:
            consume(calls)
    return sync, parallel, False

class ToolDirectingTask(Task):
    """one tool: the model writes its call. the caller runs it before asking for the next tool"""
    def __init__(self, request: ChatRequest, db, infrastructure, tool_registry, tool_names: List[str], results: str = "",
                 detected_tool_names: Optional[List[str]] = None):
        """results: what earlier tools already returned, for this call's arguments. one tool name per task.
        detected_tool_names: the laya tools in this request, which the prompt forces to be called"""
        super().__init__()
        self.results = results
        self.detected_tool_names = detected_tool_names
        self.tool_names = tool_names  # the tool to call, the prompt gets its full instructions
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
                tool_names=self.tool_names,
                detected_tool_names=self.detected_tool_names
            )

            system_prompt, context_prompt = compiler.build_prompt()
            messages = [{"role": "developer", "content": system_prompt}]
            if context_prompt:
                messages.append({"role": "developer", "content": context_prompt})
            
            detected = [name for name in (self.detected_tool_names or [])
                        if name in self.tool_names and name not in self.tool_registry.PROMPT_TOOLS]
            query = directing_query(request.content, self.tool_names, self.results, required=bool(detected))
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

    