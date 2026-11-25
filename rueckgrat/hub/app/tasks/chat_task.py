from .task_queue import Task
from ..utils.prompt_compiler import PromptCompiler
from ..utils.clock import user_timezone
from ..utils import prompts
from .tool_execution_task import ToolExecutionTask
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class ChatTask(Task):
    MIN_HISTORY = 10    # the history grows from MIN_HISTORY to MIN_HISTORY + HISTORY_STEP - 1 messages and is then cut back
    HISTORY_STEP = 10   # in one go, so the start of the chat stays the same for llama-server's prompt cache between cuts

    def __init__(self, request: ChatRequest, db, infrastructure, callback=None, tool_execution_results = None, tool_registry=None,
                 seed: Optional[int] = None):
        """tool_registry: given, the reply may call its REPLY_TOOLS at its end (MetaTask runs them).
        seed: one per turn (MetaTask: the reply's message id). the same seed every turn draws the same random numbers,
        the reply then easily follows the last reply word for word (answers the message before again). None: the conversation id"""
        super().__init__()
        self.seed = seed
        self.tool_registry = tool_registry
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.tool_execution_results = tool_execution_results
        self.callback = callback
        self.stream_id = None

    def execute(self) -> None:
        try:            
            contact = self.db.get_contact_by_id(self.request.contact_id)
            conversation = self.db.get_conversation(self.request.conversation_id)

            compiler = PromptCompiler(
                contact=contact,
                conversation=conversation,
                user_role_name=self.request.name,
                timezone=user_timezone(self.db, self.get_user_id()) if self.get_user_id() is not None else None
            )

            system_prompt, situation_prompt = compiler.build_prompt()
            if self.tool_registry:
                system_prompt += "\n\n" + self.tool_registry.reply_tools_prompt().strip()

            history, note = self.conversation_messages(self.db, self.request.conversation_id)
            messages = [{"role": "developer", "content": system_prompt}] + history

            latest = [situation_prompt, note]
            if self.tool_execution_results:
                logger.debug("adding tool outputs to chat query")
                tool_result_prompt = ToolExecutionTask.results_prompt(self.tool_execution_results)
                logger.debug(f"tool_result_prompt:\n{Utils.pretty_print(tool_result_prompt)}")
                latest.append(tool_result_prompt)
            self._add_to_latest_user_message(messages, "\n\n".join(s.strip() for s in latest if s and s.strip()))

            self.stream_id = self.infrastructure.chat(
                messages=messages,
                temperature=self.request.temperature,
                seed=self.seed if self.seed is not None else self.request.conversation_id,
                stream=True,
                callback=self.callback
            )
        except Exception as e:
            logger.error(f"failed to handle chat request {repr(e)}")

    @classmethod
    def history_size(cls, db, conversation_id: int) -> int:
        """how many of the latest messages go into the chat, see MIN_HISTORY"""
        total = db.get_message_count_by_conversation(conversation_id) or 0
        if total <= cls.MIN_HISTORY:
            return cls.MIN_HISTORY
        return cls.MIN_HISTORY + (total - cls.MIN_HISTORY) % cls.HISTORY_STEP

    def _history_size(self) -> int:
        return self.history_size(self.db, self.request.conversation_id)

    @classmethod
    def conversation_messages(cls, db, conversation_id: int) -> tuple:
        """the user and assistant messages a reply sees, and the leftover note of a trailing assistant
        answer (sources, a poll, a map, prices). same count and notes as execute, without the system
        prompt, the situation prompt or the tool results. ToolDetectionTask._pick reuses this"""
        messages, note = [], ""
        for message in db.get_messages_by_conversation(conversation_id, cls.history_size(db, conversation_id)) or []:
            content = message["content"]
            if not content:
                continue    # skip if empty to not confuse ai
            if message["role"] == "assistant":
                note = (cls._sources_line(message.get("sources")) + cls._data_lines(message.get("data") or {})).strip()
            elif message["role"] == "user" and note:
                content = f"{note}\n\n{content}"
                note = ""
            messages.append({"role": message["role"], "content": content})
        return messages, note

    @staticmethod
    def _add_to_latest_user_message(messages: list, text: str):
        """puts text in front of the content of the last user message, which is marked as the new message
        (NEW_MESSAGE_PART), a new user message when there is none"""
        if not text:
            return
        for message in reversed(messages):
            if message["role"] == "user":
                message["content"] = prompts.NEW_MESSAGE_PART.format(before=text, message=message["content"])
                return
        messages.append({"role": "user", "content": text})

    @classmethod
    def _data_lines(cls, data: dict) -> str:
        """a short line for each kind of data a past answer showed (db.set_message_data), kinds without a line are left out"""
        lines = {"poll": cls._poll_line, "map": cls._map_line, "prices": cls._prices_line}
        return "".join(line(data.get(kind)) for kind, line in lines.items())

    @staticmethod
    def _poll_line(poll) -> str:
        """one short line with the poll a past answer showed and what the user chose"""
        if not isinstance(poll, dict) or not poll.get("options"):
            return ""
        question = (poll.get("question") or "").strip()
        if question and question[-1] not in ".?!":
            question += "."
        chosen = ", ".join(poll.get("chosen") or [])
        answer = f"The user chose: {chosen}." if chosen else "The user has not answered yet."
        options = ", ".join(poll["options"])
        if not question:
            return f"\nYou asked the user a poll with these options: {options}. {answer}"
        return f"\nYou asked the user in a poll: {question} The options were: {options}. {answer}"

    @staticmethod
    def _map_line(place) -> str:
        """one short line with the place a past answer showed on a map"""
        if not isinstance(place, dict) or not place.get("display_name"):
            return ""
        return f"\nYou showed the user a map of {place['display_name']}."

    @staticmethod
    def _prices_line(prices) -> str:
        """one short line with the top three of a price ranking a past answer showed"""
        if not isinstance(prices, dict) or not prices.get("findings"):
            return ""
        top = "; ".join(f"{i}. {f.get('title')}: {f.get('price')} {f.get('currency')} at {f.get('shop')}"
                        for i, f in enumerate(prices["findings"][:3], 1))
        return f"\nYou showed the user a price ranking for {prices.get('query')}: {top}."

    @staticmethod
    def _sources_line(sources) -> str:
        """one short line naming the domains a past answer used, so the model knows its sources"""
        domains = []
        for source in sources if isinstance(sources, list) else []:
            url = source.get("url") if isinstance(source, dict) else None
            domain = urlparse(url).netloc.lower().removeprefix("www.") if isinstance(url, str) else ""
            if domain and domain not in domains:
                domains.append(domain)
        return f"\nYou looked up these sources for this answer: {', '.join(domains)}." if domains else ""

    def get_result(self) -> Dict[str, Any]:
        return None

    def has_response(self) -> bool:
        return False