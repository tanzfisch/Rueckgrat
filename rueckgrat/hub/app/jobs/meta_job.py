import re
import json
import time
import threading
from .job_queue import Job
from .chat_job import ChatJob
from .tool_directing_job import ToolDirectingJob
from .update_context_job import UpdateContextJob
from .tool_detection_job import ToolDetectionJob
from typing import Dict, Any, List, Optional

from app.common import get_logger, ChatRequest, Utils, MessageQueue
from app.utils.tts_stream import TtsStreams
logger = get_logger()

FILLERS = {
    "uh", "uhm", "um", "umm", "hm", "hmm", "mhm", "mm", "mmm", "ah", "oh", "eh", "er", "erm", "huh", "uh-huh", "aha",
    "ok", "okay", "yeah", "yea", "yep", "yup", "nope", "nah", "right", "sure", "cool", "nice", "wow", "alright",
    "thanks", "thank", "you", "thx",  # "you" only for "thank you"
    "cough", "coughs", "coughing", "sniff", "sniffs", "laughs", "laughing", "sigh", "sighs",
}

def is_trivial(text: str) -> bool:
    """a single word or only fillers (a cough, "hmm"): not worth interrupting the reply for"""
    words = re.findall(r"\w+", text.lower())
    return len(words) < 2 or all(word in FILLERS for word in words)

class Turns:
    """the MetaJob answering each conversation. a new user message either merges into it
    (that job gets cancelled, the new one answers both) or is stored as a message of its own"""

    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self._running = {}  # conversation_id -> MetaJob

    def start(self, job):
        """stores the job's user message, merged into the running turn's message while that can still be interrupted"""
        request = job.request
        with self._lock:
            previous = self._running.get(request.conversation_id)
            mergeable = previous is not None and previous.state == "running"
            merge = mergeable and not is_trivial(request.content)
            if merge:
                previous.cancelled.set()
                request.content = f"{previous.request.content} … {request.content}"
                job.user_message_id = previous.user_message_id
                self.db.update_message(job.user_message_id, request.role, request.content, request.name)
                MessageQueue().send_data({"merged": {
                    "conversation_id": request.conversation_id,
                    "user_message_id": job.user_message_id,
                    "content": request.content
                }})
                logger.info(f"follow-up merged into message {job.user_message_id}, conversation {request.conversation_id}")
            else:
                job.user_message_id = self.db.add_message(request.conversation_id, request.role, request.content, request.name)
            if merge or not mergeable:
                self._running[request.conversation_id] = job

    def busy(self, conversation_id: int) -> bool:
        """a reply is being made in this conversation"""
        with self._lock:
            return conversation_id in self._running

    def set_state(self, job, state: str) -> bool:
        """"images" (an image tool is queued) or "done" (the final goes out): from then on nothing merges into the job.
        False if the job was cancelled already"""
        with self._lock:
            if job.cancelled.is_set():
                return False
            job.state = state
            if state == "done" and self._running.get(job.request.conversation_id) is job:
                del self._running[job.request.conversation_id]
            return True

class MetaJob(Job):
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
        self.state = "running"  # "images" / "done", see Turns.set_state
        self.message_id = -1
        self.done = False

    def _update_conversation_context(self):
        udate_context_job = UpdateContextJob(self.request, self.db, self.infrastructure)
        self.add_sub_job(udate_context_job)
        self.wait_for([udate_context_job])
        new_context = udate_context_job.result()
    
        conversation = self.db.get_conversation(self.request.conversation_id)
        conversation["title"] = new_context["topic"]
        self.db.update_conversation(self.request.conversation_id, conversation["title"], json.dumps(new_context))        

    def _on_incomming_message(self, message: str):
        if self.cancelled.is_set():
            return  # late deltas of an interrupted reply
        data = json.loads(message)

        if "delta" in data:
            delta = data["delta"]
            self.db.append_to_message(self.message_id, delta)

            MessageQueue().send_data({
                "delta": delta,
                "conversation_id": self.request.conversation_id,
                "message_id": self.message_id
            })

        if data.get("error"):
            logger.error(f"chat stream failed: {data['error']}")

        if "response" in data:
            self.response["chat"] = {
                "conversation_id": self.request.conversation_id,
                "role": "assistant",
                "content": data["response"],
                "tool_calls": [],
                "message_id": self.message_id
            }
            self.done = True
            
    def _format_websearch_results(self) -> Optional[str]:
        """removes the websearch tool result from self.response, returns the WEBSEARCH_RESULT block or None"""
        if not "websearch_results" in self.response:
            return None

        websearch_response = ""
        websearch_results = self.response.pop("websearch_results")
        if len(websearch_results) > 0:
            websearch_response += f"\nWebsearch results in order of accuracy: "
            for websearch_result in websearch_results:
                websearch_response += f"\n{websearch_result['title']} - {websearch_result['answer']} - source {websearch_result['source']}"
        else:
            logger.error("empty tool response from websearch")

        if websearch_response == "":
            return None
        return f"\n\nWEBSEARCH_RESULT{websearch_response}\n"

    def _format_conversion_results(self) -> Optional[str]:
        """removes the convert tool results from self.response, returns the CONVERSION_RESULT block or None"""
        if not "conversion_results" in self.response:
            return None

        conversion_response = ""
        for conversion in self.response.pop("conversion_results"):
            if "error" in conversion:
                conversion_response += f"\n{conversion['amount']} {conversion['from']} -> {conversion['to']}: failed - {conversion['error']}"
            else:
                date = f", rate date {conversion['date']}" if "date" in conversion else ""
                conversion_response += f"\n{conversion['text']} - source {conversion['source']}{date}"

        if conversion_response == "":
            return None
        return f"\n\nCONVERSION_RESULT{conversion_response}\n"

    def _format_tool_results(self) -> Optional[str]:
        """removes the results of the simple tools (calculate, current_time, date_calc, wikipedia, weather) from self.response, returns the TOOL_RESULT block or None"""
        if not "tool_results" in self.response:
            return None

        tool_response = ""
        for tool_result in self.response.pop("tool_results"):
            if "error" in tool_result:
                tool_response += f"\n{tool_result['tool']}: failed - {tool_result['error']}"
            else:
                tool_response += f"\n{tool_result['tool']}: {tool_result['text']}"

        if tool_response == "":
            return None
        return f"\n\nTOOL_RESULT{tool_response}\n"

    def _direct_tools(self, tool_names: List[str]) -> Dict[str, Any]:
        """one tool directing call as a sub job, with the full prompts of these tools. the model writes their calls"""
        tool_directing_job = ToolDirectingJob(
            request=self.request,
            db=self.db,
            infrastructure=self.infrastructure,
            tool_registry=self.tool_registry,
            tool_names=tool_names
        )
        self.add_sub_job(tool_directing_job)
        self.wait_for([tool_directing_job])
        return tool_directing_job.result()

    def _interrupted(self) -> bool:
        """True once a follow-up was merged into this turn: drops the partial reply, the merged job answers instead"""
        if not self.cancelled.is_set():
            return False
        if self.message_id != -1:
            self.db.delete_message(self.message_id)
            TtsStreams.drop_message(self.message_id)
        MessageQueue().send_data({"cancelled": {
            "conversation_id": self.request.conversation_id,
            "message_id": self.message_id if self.message_id != -1 else None
        }})
        logger.info(f"reply interrupted by a follow-up, conversation {self.request.conversation_id}")
        return True

    def execute(self) -> None:
        self.response = {}

        if self.db.get_message_count_by_conversation(self.request.conversation_id) <= 1:
            MessageQueue().send_status_message("creating scenario")
        else:
            MessageQueue().send_status_message("update context")

        # run this in parallel to updateing the context
        tool_detection_job = ToolDetectionJob(self.request.content, self.tool_registry, self.infrastructure)
        self.add_sub_job(tool_detection_job)

        self._update_conversation_context() # update context after user message was added
        if self._interrupted():
            return

        try:
            MessageQueue().send_status_message("thinking")
            self.wait_for([tool_detection_job])
            tool_names = tool_detection_job.result()
            logger.info(f"tools detected: {tool_names}")
            
            tool_names = (tool_names or []) + self.tool_registry.PROMPT_TOOLS
            contact = self.db.get_contact_by_id(self.request.contact_id)

            tool_calls, compiled_response = [], ""
            if tool_names:
                tool_response = self._direct_tools(tool_names)
                tool_calls, compiled_response = tool_response["tool_calls"], tool_response["content"]
            if self._interrupted():
                return

            self.tool_registry.execute(
                user_id=self.user_id,
                contact_id=self.request.contact_id,
                conversation_id=self.request.conversation_id,
                response=self.response,
                tool_calls=tool_calls,
                parallel=False
            )

            MessageQueue().send_status_message("compile response")

            websearch_block = self._format_websearch_results()
            if websearch_block:
                compiled_response += websearch_block

            conversion_block = self._format_conversion_results()
            if conversion_block:
                compiled_response += conversion_block

            tool_block = self._format_tool_results()
            if tool_block:
                compiled_response += tool_block
            
            #logger.debug(f"compiled response:\n{compiled_response}")
            if self._interrupted():
                return

            contact_name = Utils.get_nested_value(contact, ["identity", "name"])
            self.message_id = self.db.add_message(self.request.conversation_id, "assistant", "", contact_name)

            # once an image is queued the reply can't be interrupted anymore, a follow-up is a new message then
            if any(self.tool_registry.parallel.get(call["tool"]) for call in tool_calls) and not self.turns.set_state(self, "images"):
                self._interrupted()
                return

            # the parallel tools (take_photo, generate_image) attach their images to the new message themselves
            parallel_tool_calls = [{**tool_call, "message_id": self.message_id} for tool_call in tool_calls]
            self.tool_registry.execute(
                user_id=self.user_id,
                contact_id=self.request.contact_id,
                conversation_id=self.request.conversation_id,
                response=self.response,
                tool_calls=parallel_tool_calls,
                parallel=True
            )

            MessageQueue().send_status_message("finalize answer")

            chat_job = ChatJob(
                request=self.request,
                db=self.db,
                infrastructure=self.infrastructure, 
                callback=self._on_incomming_message,
                thinking_response=compiled_response
            )

            self.add_sub_job(chat_job)
            self.wait_for([chat_job])

            logger.debug("assistant response generated")

            start = time.time()
            while not self.done:
                if self.cancelled.is_set():
                    self.infrastructure.cancel(chat_job.stream_id)
                    break
                if time.time() - start > 300:
                    raise TimeoutError("5 min timeout")
                time.sleep(0.01)

            if not self.turns.set_state(self, "done"):
                self._interrupted()
                return

            MessageQueue().set_status("done")

        except Exception as e:
            logger.error(f"failed to execute MetaJob {repr(e)}")
        finally:
            self.turns.set_state(self, "done")

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return not self.cancelled.is_set()