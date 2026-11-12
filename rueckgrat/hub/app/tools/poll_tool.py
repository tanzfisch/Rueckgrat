from typing import Dict, Any, Optional
from .tool import Tool
from . import prompts

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_OPTIONS = 8
MAX_QUESTION_LENGTH = 200
MAX_OPTION_LENGTH = 80

class PollTool(Tool):
    description = prompts.POLL_DESCRIPTION
    question = [
        "Does the user ask for a poll, a vote, a quiz or a multiple choice question?",
        "Does the user ask to be given options or choices to pick from?",
        "Does the user ask your to create a questionnaire?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "poll"

    def _make_poll(self, tool_call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

    def execute(self) -> None:
        poll = self._make_poll(self.tool_call)
        if poll is None:
            logger.error(f"invalid poll: {self.tool_call}")
            return
        
        MessageQueue().send_status_message("making a poll")
        if self.has_message():
            self.db.set_message_poll(self.message_id, poll)
            self.push("poll", poll=poll)
        self.add_result({"tool": self.name(), "text": self._text(poll), "form": poll})

    def planned_text(self) -> str:
        poll = self._make_poll(self.tool_call)
        return self._text(poll) if poll else prompts.POLL_INVALID_PART

    @staticmethod
    def _text(poll: Dict[str, Any]) -> str:
        return prompts.POLL_SHOWN_PART.format(
            question=poll['question'],
            choices=prompts.POLL_ONE_CHOICE_PART if poll['mode'] == 'single' else prompts.POLL_SEVERAL_CHOICES_PART,
            options=' | '.join(poll['options']))

    @classmethod
    def prompt(cls) -> str:
        return prompts.POLL_PROMPT
