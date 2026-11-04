from typing import Dict, Any, Optional
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_OPTIONS = 8
MAX_QUESTION_LENGTH = 200
MAX_OPTION_LENGTH = 80


def make_poll(tool_call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """the poll of a tool call: {"question", "options", "mode": "single"|"multi"}, None if the call is invalid.
    options are trimmed, duplicates dropped, a poll needs 2 to MAX_OPTIONS of them"""
    question = " ".join(str(tool_call.get("question") or "").split())
    options = tool_call.get("options")
    if not question or len(question) > MAX_QUESTION_LENGTH or not isinstance(options, list):
        return None
    cleaned = []
    for option in options:
        option = " ".join(str(option).split()) if isinstance(option, (str, int, float)) else ""
        if option and len(option) <= MAX_OPTION_LENGTH and option.lower() not in (o.lower() for o in cleaned):
            cleaned.append(option)
    if not 2 <= len(cleaned) <= MAX_OPTIONS:
        return None
    mode = "multi" if str(tool_call.get("mode") or "").lower() == "multi" else "single"
    return {"question": question, "options": cleaned, "mode": mode}


class PollTool(Tool):
    category = ToolCategory.GENERAL
    description = "shows the user a poll bubble with options to tap, one choice or several"
    question = [
        "Does the user ask for a poll, a vote, a quiz or a multiple choice question?",
        "Does the user ask to be given options or choices to pick from?",
        "Does the user ask your to create a questionnaire?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "poll"

    def execute(self) -> None:
        poll = make_poll(self.tool_call)
        if poll is None:
            logger.error(f"invalid poll: {self.tool_call}")
            result = {"tool": self.name(), "error": "no poll shown, it needs a question and 2 to 8 options"}
        elif "poll" in self.response:
            result = {"tool": self.name(), "error": "only one poll per message, the first one is shown"}
        else:
            MessageQueue().send_status_message("making a poll")
            self.response["poll"] = poll    # MetaTask stores it with the answer message and sends it with the final "chat"
            result = {"tool": self.name(), "text": f"the poll is shown to the user: \"{poll['question']}\" "
                      f"({'one choice' if poll['mode'] == 'single' else 'several choices'}: {' | '.join(poll['options'])}). "
                      "Do not write the question, the options or further questions in your answer text, they are only in the tool call. At most one short line that points to the poll."}
        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
POLL:
Use when the user asks for a poll, a vote, a quiz or options to choose from, or when a multiple choice question fits your answer better than an open question. The user picks from the options, the choice comes back as their next message.

Parameters:
- question (string, required): the question, short
- options (list of strings, required): 2 to 8 short options
- mode (string, optional): "single" (one choice, default) or "multi" (several choices)

Put the question and the options only in the tool call. Do not write them or a list of further questions in your answer text, at most one short line that points to the poll.
One poll per message: for a questionnaire or quiz, put the first question in the poll and ask the next one in a new poll after the user answered.

Example:
{"tool": "poll", "question": "Where should we go tonight?", "options": ["Cinema", "Restaurant", "Stay home"], "mode": "single"}
"""
