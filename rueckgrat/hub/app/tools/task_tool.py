from typing import Dict, Any
from .tool import Tool
from . import prompts
from app.companion.user_tasks import UserTasks, TaskError, TaskNotFound, schedules

from app.common import get_logger, MessageQueue
logger = get_logger()


class TaskTool(Tool):
    """#170 the user's tasks with this contact: something it does at a set time, once or repeating (UserTasks). at its time
    CompanionScheduler runs it as a TaskJob and the contact writes the result into the conversation"""
    description = prompts.TASK_DESCRIPTION
    thresholds = (0.65, 0.7)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [    # no "remind" question: laya mixes it up with "remember" (the remember tool)
        "Does the user want an alarm to ring at a certain time?",
        "Does the user want to see, move or cancel one of their reminders or alarms?",
        "Is the user telling you to monitor something and alert them when it changes?",
        "Does the user ask which reminders or alarms they have?",
        "Does the user tell you when to act, using words like every, hourly, daily or in 2 hours?",
        "Does the user ask you to do a task for them later, like in 45 minutes or in 2 hours?",
    ]

    tasks: UserTasks = None     # set at hub start (main.py): the same UserTasks as the /tasks routes, it wakes the scheduler

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def takes_over(cls, prompt: str) -> bool:
        """only a message that says when to act makes a task of work that a background job does now (a build that ends
        with "tell me when it works" is a job, "check it every hour" a task)"""
        return schedules(prompt)

    @classmethod
    def name(cls) -> str:
        return "task"

    @classmethod
    def user_tasks(cls, db) -> UserTasks:
        """the hub's UserTasks, one of its own without a hub (tests, hub management)"""
        return cls.tasks if cls.tasks is not None else UserTasks(db)

    def execute(self) -> None:
        action = str(self.tool_call.get("action") or "create").strip().lower()
        tasks = self.user_tasks(self.db)
        MessageQueue().send_status_message("planning a task" if action == "create" else "looking at the tasks")
        try:
            text = self._run(tasks, action)
            self.add_result({"tool": self.name(), "text": text})
        except (TaskError, TaskNotFound) as e:
            logger.info(f"task {action}: {e}")
            self.add_result({"tool": self.name(), "error": str(e)})
        except Exception as e:
            logger.error(f"task {action} failed {repr(e)}")
            self.add_result({"tool": self.name(), "error": "the task could not be handled"})

    def _run(self, tasks: UserTasks, action: str) -> str:
        call, user_id = self.tool_call, self.get_user_id()
        if action in ("create", "add", "new", "set"):
            task = tasks.create(user_id, self.contact_id, call.get("task"), call.get("when"), call.get("repeat"),
                                call.get("alarm", False), self.get_conversation_id())
            text = prompts.TASK_CREATED_PART.format(id=task["id"], task=tasks.describe(task))
            return text + (prompts.TASK_COMPANION_PART if task["companion_switched_on"] else "")
        if action in ("list", "show"):
            mine = tasks.list(user_id, self.contact_id)
            others = len(tasks.list(user_id)) - len(mine)
            text = prompts.TASK_LIST_PART.format(tasks="\n".join(prompts.TASK_LINE.format(task=tasks.describe(t)) for t in mine)) \
                if mine else prompts.TASK_NONE_PART
            return text + (prompts.TASK_OTHERS_PART.format(count=others) if others else "")
        if action not in ("edit", "change", "update", "cancel", "delete", "remove", "stop"):
            raise TaskError(prompts.TASK_UNKNOWN_ACTION_PART.format(action=action))
        task_id = self._task_id(tasks, user_id)
        if action in ("cancel", "delete", "remove", "stop"):
            return prompts.TASK_CANCELLED_PART.format(id=task_id, task=tasks.describe(tasks.cancel(user_id, task_id)))
        task = tasks.edit(user_id, task_id, call.get("task"), call.get("when"), call.get("repeat"), call.get("alarm"))
        return prompts.TASK_CHANGED_PART.format(id=task_id, task=tasks.describe(task))

    def _task_id(self, tasks: UserTasks, user_id: int) -> int:
        """the call's id ("3", "#3"), a task of this contact"""
        try:
            task_id = int(str(self.tool_call.get("id") or "").strip().lstrip("#"))
        except ValueError:
            raise TaskError(prompts.TASK_NO_ID_PART)
        if tasks.get(user_id, task_id)["contact_id"] != self.contact_id:
            raise TaskNotFound(f"task #{task_id} is not one of yours, it is on the tasks page of the app")
        return task_id

    @classmethod
    def prompt(cls, open_tasks: str = "") -> str:
        return prompts.TASK_PROMPT.format(open_tasks=open_tasks)

    @classmethod
    def prompt_for(cls, user_id: int, contact_id: int, conversation_id: int) -> str:
        """the prompt with the contact's open tasks, so a cancel or change knows their ids"""
        if cls.tasks is None:
            return cls.prompt()
        try:
            listed = "\n".join(prompts.TASK_LINE.format(task=cls.tasks.describe(t)) for t in cls.tasks.list(user_id, contact_id)) or "  none"
        except Exception as e:
            logger.warning(f"tasks of contact {contact_id} not listed {repr(e)}")
            return cls.prompt()
        return cls.prompt(prompts.TASK_OPEN_PART.format(tasks=listed, max_tasks=cls.tasks.max_tasks, min_interval=cls.tasks.min_interval))
