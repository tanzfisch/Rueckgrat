from .tool import Tool
from . import prompts


class FindToolsTool(Tool):
    """asks for another tool detection: the setup names a task that needs a tool it was not offered (the quiz goes on
    with the next poll after a three word answer). ToolExecutionTask runs the detection on the task and offers what it
    finds in extra rounds (find_tools_steps), this call only notes the task for the reply"""
    description = prompts.FIND_TOOLS_DESCRIPTION
    question = []

    @classmethod
    def name(cls) -> str:
        return "find_tools"

    def execute(self) -> None:
        task = self.task(self.tool_call)
        if not task:
            self.add_result({"tool": self.name(), "error": "no task given"})
            return
        self.add_result({"tool": self.name(), "text": prompts.FIND_TOOLS_PART.format(task=task)})

    @staticmethod
    def task(call: dict) -> str:
        """the task of a call, one line"""
        return " ".join(str(call.get("task") or "").split())

    @classmethod
    def prompt(cls) -> str:
        return prompts.FIND_TOOLS_PROMPT
