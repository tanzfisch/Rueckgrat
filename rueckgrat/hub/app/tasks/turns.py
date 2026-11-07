import re
import threading

from app.common import get_logger, MessageQueue
logger = get_logger()

class Turns:
    """a turn represents the user's message and the reply to it"""

    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self._running = {}

    def start(self, task):
        """stores the task's user message, merged into the running turn's message while that can still be interrupted"""
        request = task.request
        with self._lock:
            previous = self._running.get(request.conversation_id)
            mergeable = previous is not None and previous.state == "running"
            merge = mergeable and not self._is_trivial(request.content)
            if merge:
                previous.cancelled.set()
                request.content = f"{previous.request.content} … {request.content}"
                task.user_message_id = previous.user_message_id
                self.db.update_message(task.user_message_id, request.role, request.content, request.name)
                MessageQueue().send_data({"merged": {
                    "conversation_id": request.conversation_id,
                    "user_message_id": task.user_message_id,
                    "content": request.content
                }}, user_id=task.user_id)   # runs on the websocket loop, not in a task
                logger.info(f"follow-up merged into message {task.user_message_id}, conversation {request.conversation_id}")
            else:
                task.user_message_id = self.db.add_message(request.conversation_id, request.role, request.content, request.name)
            if merge or not mergeable:
                self._running[request.conversation_id] = task

    def busy(self, conversation_id: int) -> bool:
        """a reply is being made in this conversation"""
        with self._lock:
            return conversation_id in self._running

    def any_busy(self) -> bool:
        """a reply is being made in any conversation"""
        with self._lock:
            return bool(self._running)

    def set_state(self, task, state: str) -> bool:
        """"detached" (a detached tool call writes to the message) or "done" (the final goes out): from then on nothing merges into the task.
        False if the task was cancelled already"""
        with self._lock:
            if task.cancelled.is_set():
                return False
            task.state = state
            if state == "done" and self._running.get(task.request.conversation_id) is task:
                del self._running[task.request.conversation_id]
            return True

    def _is_trivial(self, text: str) -> bool:
        FILLERS = {
            "uh", "uhm", "um", "umm", "hm", "hmm", "mhm", "mm", "mmm", "ah", "oh", "eh", "er", "erm", "huh", "uh-huh", "aha",
            "ok", "okay", "yeah", "yea", "yep", "yup", "nope", "nah", "right", "sure", "cool", "nice", "wow", "alright",
            "thanks", "thank", "you", "thx", "cough", "coughs", "coughing", "sniff", "sniffs", "laughs", "laughing", "sigh", "sighs",
        }
        words = re.findall(r"\w+", text.lower())
        return len(words) < 2 or all(word in FILLERS for word in words)
