import json
import time
import threading
from .task_queue import Task
from .chat_task import ChatTask
from .update_context_task import UpdateContextTask
from .tool_detection_task import ToolDetectionTask
from .tool_execution_task import ToolExecutionTask
from typing import Dict, Any

from app.common import get_logger, ChatRequest, Utils, MessageQueue
from app.utils.tts_stream import TtsStreams
from app.utils.conversation_volume import ConversationVolume
logger = get_logger()

class MetaTask(Task):
    def __init__(self, user_id: int, request: ChatRequest, db, infrastructure, tool_registry, turns):
        super().__init__()
        self.user_id = user_id
        self.request = request
        self.db = db
        self.infrastructure = infrastructure     
        self.tool_registry = tool_registry
        self.turns = turns
        self.user_message_id = None  # stored by Turns.start, merged follow-ups update it
        self.cancelled = threading.Event()  # set when a follow-up merged into this turn
        self.state = "running"  # "detached" / "done", see Turns.set_state
        self.message_id = -1
        self.sources = []   # pages the web tools used, shown as links under the answer
        self.reply = ""     # the reply streamed so far, with the tool calls at its end
        self.streamed = ""  # the part of it sent to the user, without the tool calls
        self.reply_calls = []   # the REPLY_TOOLS calls the reply wrote
        self.done = False

    def _on_incomming_message(self, message: str):
        if self.cancelled.is_set():
            return  # late deltas of an interrupted reply
        data = json.loads(message)

        if "delta" in data:
            self.reply += data["delta"]
            visible, _ = self.tool_registry.split_reply(self.reply, final=False)
            self._send_delta(visible)

        if data.get("error"):
            logger.error(f"chat stream failed: {data['error']}")

        if "response" in data:
            visible, self.reply_calls = self.tool_registry.split_reply(data["response"])
            self._send_delta(visible)
            self.response["chat"] = {
                "conversation_id": self.request.conversation_id,
                "role": "assistant",
                "content": visible,
                "tool_calls": [],
                "message_id": self.message_id,
                "sources": self.sources
            }
            self.done = True
    
    def _send_delta(self, visible: str):
        """stores and sends what of the visible reply was not sent yet"""
        delta = visible[len(self.streamed):]
        if not delta:
            return
        self.streamed = visible
        self.db.append_to_message(self.message_id, delta)

        MessageQueue().send_data({
            "delta": delta,
            "conversation_id": self.request.conversation_id,
            "message_id": self.message_id
        }, user_id=self.user_id)   # called on the node's websocket thread, no task context there

    def _run_reply_tools(self):
        """runs the REPLY_TOOLS calls the reply wrote, they are detached and write to the reply's message"""
        logger.debug(f"reply tool calls: {self.reply_calls}")
        task = ToolExecutionTask(
            user_id = self.user_id,
            request = self.request,
            context = None,
            db = self.db,
            infrastructure = self.infrastructure,
            tool_registry = self.tool_registry,
            tool_names = [],
            message_id = self.message_id,
            detach = lambda: self.turns.set_state(self, "detached"),
            tool_calls = self.reply_calls
        )
        self.add_sub_task(task)
        self.wait_for([task])

    def _interrupted(self) -> bool:
        """True once a follow-up was merged into this turn: drops the partial reply, the merged task answers instead"""
        if not self.cancelled.is_set():
            return False
        if self.message_id != -1:
            self.db.delete_message(self.message_id)
            TtsStreams.drop_message(self.message_id)
            from app.utils.text_files import remove_message_files
            remove_message_files(self.user_id, self.request.conversation_id, self.message_id)
        MessageQueue().send_data({"cancelled": {
            "conversation_id": self.request.conversation_id,
            "message_id": self.message_id if self.message_id != -1 else None
        }}, user_id=self.user_id)
        logger.info(f"reply interrupted by a follow-up, conversation {self.request.conversation_id}")
        return True

    def execute(self) -> None:
        self.response = {}

        MessageQueue().send_status_message("thinking")
        tool_detection_task = ToolDetectionTask(self.request.content, self.tool_registry, self.infrastructure,
                                                volume=ConversationVolume(self.user_id, self.request.conversation_id))
        self.add_sub_task(tool_detection_task)        

        if self._interrupted():
            return

        try:            
            self.wait_for([tool_detection_task])
            detected = tool_detection_task.get_result() or []
            logger.debug(f"tools detected: {detected}")
            tool_detection_task.trace(self.request.conversation_id, "turn")

            contact = self.db.get_contact_by_id(self.request.contact_id)
            contact_name = Utils.get_nested_value(contact, ["identity", "name"])
            self.message_id = self.db.add_message(self.request.conversation_id, "assistant", "", contact_name)

            tool_execution_task = ToolExecutionTask(
                user_id = self.user_id, 
                request = self.request, 
                context = Utils.get_nested_value(self.db.get_conversation(self.request.conversation_id), ["context"], ""),
                db = self.db, 
                infrastructure = self.infrastructure, 
                tool_registry = self.tool_registry, 
                tool_names = detected["tool_names"],
                recommended_tools = detected.get("recommended") or [],
                excluded_tools = self.tool_registry.REPLY_TOOLS,  # the reply calls these itself, see _run_reply_tools
                message_id = self.message_id,
                detach = lambda: self.turns.set_state(self, "detached"),
                history = 2     # the setup sees the last answer and the message before it: a quiz goes on
            )
            
            self.add_sub_task(tool_execution_task)
            self.wait_for([tool_execution_task])
            tool_execution_results = tool_execution_task.get_result() or {}
            #logger.debug(f"Tool execution results:\n{Utils.pretty_print(tool_execution_results)}")

            if self._interrupted():
                return

            if "wikipedia" in tool_execution_results:
                self.sources += tool_execution_results["wikipedia"]["sources"]

            if "fetch_url" in tool_execution_results:
                self.sources += tool_execution_results["fetch_url"]["sources"]

            if "websearch" in tool_execution_results:
                self.sources += tool_execution_results["websearch"]["sources"]                

            if self.sources and len(self.sources) > 0:
                self.db.set_message_sources(self.message_id, self.sources)

            MessageQueue().send_status_message("finalize answer")

            chat_task = ChatTask(
                request=self.request,
                db=self.db,
                infrastructure=self.infrastructure, 
                callback=self._on_incomming_message,
                tool_execution_results=tool_execution_results,
                tool_registry=self.tool_registry
            )

            self.add_sub_task(chat_task)
            self.wait_for([chat_task])

            logger.debug("assistant response generated")

            start = time.time()
            while not self.done:
                if self.cancelled.is_set():
                    self.infrastructure.cancel(chat_task.stream_id)
                    break
                if time.time() - start > 300:
                    raise TimeoutError("5 min timeout")
                time.sleep(0.01)

            if self.reply_calls and not self.cancelled.is_set():
                self._run_reply_tools()

            if not self.turns.set_state(self, "done"):
                self._interrupted()
                return

            MessageQueue().set_status("done")            
            self.add_sub_task(UpdateContextTask(self.request, self.db, self.infrastructure))

        except Exception as e:
            logger.error(f"failed to execute MetaTask {repr(e)}")
        finally:
            self.turns.set_state(self, "done")

    def get_result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return not self.cancelled.is_set()
