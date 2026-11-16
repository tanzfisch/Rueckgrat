from app.tasks.task_queue import Task
from . import prompts
from contextlib import nullcontext
from typing import Dict, Any, Optional, List

from app.common import get_logger, MessageQueue
logger = get_logger()

class Tool(Task):
    description = ""    # one line for the tool index, every tool sets its own
    question = []       # yes/no decision questions: does the request involve this tool's purpose. the tool counts with its most likely question
    thresholds = None   # (recommended, mandatory) for the question scores, None: ToolDetectionTask's RECOMMENDED_THRESHOLD and MANDATORY_THRESHOLD
    sequential = False  # the calls of sequential tools in one round run one after another in their order (they share the sandbox files)
    offered_with = ()   # names of tools this one is offered with as an optional tool (ToolRegistry.companions), no laya question of its own
    requires = ()       # the capabilities it needs (Infrastructure.available: "image", "embedding", "internet" ...), without one it is not offered

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__()
        self.db = db
        self.infrastructure = infrastructure
        self.user_id=user_id
        self.contact_id=contact_id
        self.conversation_id=conversation_id
        self.tool_call=tool_call
        self._response: Dict[str, Any] = {}
        self.message_id: Optional[int] = None

    def get_result(self) -> Dict[str, Any]:
        return dict(self._response)

    def add_result(self, result: Dict[str, Any]) -> None:
        self._response.setdefault(self.name(), {}).update(result)

    def add_source(self, url: str, title: str = ""):
        data = self._response.setdefault(self.name(), {})
        sources = data.setdefault("sources", [])
        if url and all(source["url"] != url for source in sources):
            sources.append({"url": url, "title": title})

    def has_message(self) -> bool:
        """the call is for a stored assistant message (not an agent job's worker or a companion that holds its result)"""
        return self.message_id is not None and self.message_id >= 0

    def show_data(self, kind: str, value) -> None:
        """stores value as the data of kind of this call's message and sends it to the chat, e.g. show_data("poll", {...}).
        the client shows it under the bubble by its kind. nothing without a stored message (a worker's or companion's call)"""
        if not self.has_message():
            return
        self.db.set_message_data(self.message_id, kind, value)
        MessageQueue().send_data({"data": {"conversation_id": self.conversation_id, "message_id": self.message_id, "kind": kind, "value": value}},
                                 user_id=self.user_id)

    @classmethod
    def sharing(cls):
        """the context around a round's sequential calls of this tool (ToolRegistry._run_lane), e.g. one sandbox for all"""
        return nullcontext()

    def runs_detached(self) -> bool:
        """a call of a DETACHED_TOOLS tool runs in the background. False keeps this call in its round"""
        return True

    def planned_result(self) -> Dict[str, Any]:
        """the result the reply gets while this call runs detached (ToolRegistry.DETACHED_TOOLS), made from the call alone"""
        return {self.name(): {"tool": self.name(), "text": self.planned_text()}}

    def planned_text(self) -> str:
        return prompts.TOOL_PLANNED_PART.format(name=self.name())

    @classmethod
    def attach_held(cls, db, user_id: int, conversation_id: int, message_id: int, held: Dict[str, Any], push: bool) -> None:
        """attaches one file this tool held without a message (an item of its result's "attachments": {"tool", "name", ...})
        to message_id. only tools that hold files have it"""
        raise NotImplementedError(f"{cls.__name__} holds no attachments")

    @classmethod
    def problems(cls, result: Dict[str, Any]) -> List[str]:
        """what went wrong in one result of this tool that another try could fix (a worker's fix rounds, see
        ToolExecutionTask). most tools have nothing to fix: []"""
        return []

    @classmethod
    def merge(cls, known: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """combines two results of this tool from one message: the texts on separate lines, lists added up,
        every other key of the later result replaces the earlier one"""
        combined = {**known, **result}
        if known.get("text") and result.get("text"):
            combined["text"] = f"{known['text']}\n{result['text']}"
        for key, value in known.items():
            if isinstance(value, list) and isinstance(result.get(key), list):
                combined[key] = value + result[key]
        return combined

    @classmethod
    def name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def prompt(cls) -> str:
        raise NotImplementedError

    @classmethod
    def prompt_for(cls, user_id: int, contact_id: int, conversation_id: int) -> str:
        """the prompt for one conversation's tool setup (ToolRegistry.get_tools_prompt with a scope), e.g. with what
        the contact's files hold. most tools have one prompt for all: prompt()"""
        return cls.prompt()

    @classmethod
    def get_description(cls) -> str:
        """the one line for the tool index. fallback: first prompt line that is not a "HEADER:" line"""
        if cls.description:
            return cls.description
        for line in cls.prompt().splitlines():
            line = line.strip()
            if line and not line.endswith(":"):
                return line
        return cls.name()
    
    def has_response(self) -> bool:
        return False    