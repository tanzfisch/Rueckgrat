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
from app.utils.sandbox_volume import SandboxVolume
logger = get_logger()

class MetaTask(Task):
    SETUP_HISTORY = 2    # earlier turns the setup prompt sees (a chat turn; laya_tune can recommend a change)

    def __init__(self, user_id: int, request: ChatRequest, db, infrastructure, tool_registry, turns):
        super().__init__(user_id=user_id)
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

    def get_conversation_id(self) -> int:
        """its status messages carry the conversation of its request"""
        return self.request.conversation_id

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
        }, user_id=self.get_user_id(), session=self.get_session())   # called on the node's websocket thread, no task context there

    def _run_reply_tools(self):
        """runs the REPLY_TOOLS calls the reply wrote, they are detached and write to the reply's message"""
        logger.debug(f"reply tool calls: {self.reply_calls}")
        task = ToolExecutionTask(
            user_id = self.get_user_id(),
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

    def _drop_reply(self):
        """removes the reply (message, speech, files) and tells the client the message is gone"""
        if self.message_id != -1:
            self.db.delete_message(self.message_id)
            TtsStreams.drop_message(self.message_id)
            from app.utils.text_files import remove_message_files
            remove_message_files(self.get_user_id(), self.request.conversation_id, self.message_id)
        MessageQueue().send_data({"cancelled": {
            "conversation_id": self.request.conversation_id,
            "message_id": self.message_id if self.message_id != -1 else None
        }}, user_id=self.get_user_id())

    def _interrupted(self) -> bool:
        """True once a follow-up was merged into this turn: drops the partial reply, the merged task answers instead"""
        if not self.cancelled.is_set():
            return False
        self._drop_reply()
        logger.info(f"reply interrupted by a follow-up, conversation {self.request.conversation_id}")
        return True

    def _blank(self) -> bool:
        """True when the reply shows nothing: no text and no call but remember (a photo is shown, the memory is not)"""
        return not self.streamed and all(call.get("tool") == "remember" for call in self.reply_calls)

    def _answer(self, tool_execution_results: dict, attempt: int = 0):
        """the model writes the reply from the tool results, returns when it is done or a follow-up cancelled it.
        attempt: a new try draws other random numbers (the seed of the same turn would write the same empty reply)"""
        self.reply, self.streamed, self.reply_calls, self.done, self.response = "", "", [], False, {}
        chat_task = ChatTask(
            request=self.request,
            db=self.db,
            infrastructure=self.infrastructure,
            callback=self._on_incomming_message,
            tool_execution_results=tool_execution_results,
            tool_registry=self.tool_registry,
            seed=self.message_id + attempt    # one per turn, see ChatTask. the next id is a user message, never a reply's seed
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

    def _detection_task(self, volume=None) -> ToolDetectionTask:
        """the turn's tool detection (same excluded tools as a chat turn). volume: the contact's files, None when
        the stack has no sandbox (laya_tune); execute() passes the contact's SandboxVolume"""
        return ToolDetectionTask(self.request.content, self.tool_registry, self.infrastructure,
                                 excluded_tools=self.tool_registry.CHAT_EXCLUDED_TOOLS,
                                 volume=volume, db=self.db, conversation_id=self.request.conversation_id)

    def _setup_task(self, detected: dict, message_id=None, detach=None) -> ToolExecutionTask:
        """the setup rounds for a detection, the same exclusions as a chat turn. message_id and detach are for
        a stored reply (execute()); laya_tune's stack mode passes neither"""
        context = ""
        if self.db is not None:
            conversation = self.db.get_conversation(self.request.conversation_id)
            context = Utils.get_nested_value(conversation, ["context"], "") if conversation else ""
        return ToolExecutionTask(
            user_id=self.get_user_id(),
            request=self.request,
            context=context,
            db=self.db,
            infrastructure=self.infrastructure,
            tool_registry=self.tool_registry,
            tool_names=(detected or {}).get("tool_names"),
            recommended_tools=(detected or {}).get("recommended") or [],
            excluded_tools=self.tool_registry.REPLY_TOOLS + self.tool_registry.CHAT_EXCLUDED_TOOLS,
            message_id=message_id,
            detach=detach,
            history=self.SETUP_HISTORY,
        )

    def detect_and_setup(self) -> Dict[str, Any]:
        """tool detection and the setup rounds of a chat turn, without a reply or a stored message (laya_tune's
        stack mode). the tools are not executed when the registry's execute_tools is off. returns the detection source,
        the bands, the scores, and the calls the model wrote"""
        queue = self.tool_registry.task_queue
        if queue is None:
            raise RuntimeError("tool registry has no task queue")
        detection = self._detection_task()
        if not queue.run(detection):
            raise RuntimeError("tool detection failed")
        detected = detection.get_result() or {}
        setup = self._setup_task(detected)
        if not queue.run(setup):
            raise RuntimeError("tool setup failed")
        calls = [item["call"] for item in setup.get_executed()]
        return {
            "source": detection.source(),
            "tool_names": detected.get("tool_names") or [],
            "recommended": detected.get("recommended") or [],
            "offered_mandatory": setup.get_tool_names(),
            "offered_recommended": setup.get_recommended(),
            "scores": detection.tool_scores(),
            "laya_scores": detection.laya_scores(),
            "text_scores": detection.text_score_values(),
            "followup_score": detection.followup_score(),
            "gate": detection.gate_probabilities(),
            "project": detection.project_score(),
            "picked": detection.picked_tools(),
            "calls": calls,
            "called": list(dict.fromkeys(call.get("tool") for call in calls if call.get("tool"))),
            "executed": setup.get_executed(),
            "results": setup.get_result() or {},
        }

    def execute(self) -> None:
        self.response = {}

        MessageQueue().send_status_message("thinking")
        tool_detection_task = self._detection_task(volume=SandboxVolume(self.get_user_id(), self.request.contact_id))
        self.add_sub_task(tool_detection_task)        

        if self._interrupted():
            return

        try:            
            self.wait_for([tool_detection_task])
            detected = tool_detection_task.get_result() or []
            logger.debug(f"tools detected ({tool_detection_task.source() or 'nothing decided'}): {detected}")
            tool_detection_task.trace(self.request.conversation_id, "turn")

            contact = self.db.get_contact_by_id(self.request.contact_id)
            contact_name = Utils.get_nested_value(contact, ["identity", "name"])
            self.message_id = self.db.add_message(self.request.conversation_id, "assistant", "", contact_name)

            tool_execution_task = self._setup_task(
                detected,
                message_id=self.message_id,
                detach=lambda: self.turns.set_state(self, "detached"),
            )
            
            self.add_sub_task(tool_execution_task)
            self.wait_for([tool_execution_task])
            tool_execution_results = tool_execution_task.get_result() or {}
            #logger.debug(f"Tool execution results:\n{Utils.pretty_print(tool_execution_results)}")

            if self._interrupted():
                return

            if "fetch_url" in tool_execution_results:
                self.sources += tool_execution_results["fetch_url"]["sources"]

            if "websearch" in tool_execution_results:
                self.sources += tool_execution_results["websearch"]["sources"]                

            if self.sources and len(self.sources) > 0:
                self.db.set_message_sources(self.message_id, self.sources)

            MessageQueue().send_status_message("finalize answer")

            self._answer(tool_execution_results)
            if not self.cancelled.is_set() and self._blank():
                # nothing to show (the model wrote only a call, or a cut off one): once more, the user is not told
                logger.error(f"empty reply, conversation {self.request.conversation_id}: answering again")
                self._answer(tool_execution_results, attempt=1)
                if not self.cancelled.is_set() and self._blank():
                    logger.error(f"empty reply again, conversation {self.request.conversation_id}: dropped")
                    self._drop_reply()
                    self.response, self.reply_calls = {}, []

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
        return bool(self.response) and not self.cancelled.is_set()   # a dropped empty reply sends nothing
