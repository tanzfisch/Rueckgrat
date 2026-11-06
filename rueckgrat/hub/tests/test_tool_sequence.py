"""tool sequence: laya-detected tools are one request each, in order, with results forwarded. optional tools
(PROMPT_TOOLS, and a worker's always-on websearch) are one combined request after that. the answer is finalized
only after both. an empty optional answer calls nothing and is not a failure.

run from rueckgrat/hub (pytest.ini puts the hub on the path). no network and no model calls.
"""
import json

import pytest

from app.agent_jobs.agent_job import AgentJob
from app.common import ChatRequest, MessageQueue
from app.tasks.meta_task import MetaTask
from app.tasks.task_queue import Task, TaskQueue
from app.tasks.tool_directing_task import ToolDirectingTask, directing_query, run_tool_sequence
from app.tools.tool_registry import ToolRegistry


@pytest.fixture(scope="module")
def registry():
    return ToolRegistry(None, None, None)


def test_ordered_names_convert_before_calculate_and_lookup_tuple(registry):
    assert registry.ordered_names(["calculate", "convert", "calculate"]) == ["convert", "calculate"]
    assert registry.ordered_names(["weather", "fetch_url", "websearch", "wikipedia"]) == [
        "wikipedia", "websearch", "fetch_url", "weather"]
    assert registry.ordered_names(["take_photo", "calculate", "generate_image", "convert"]) == [
        "convert", "calculate", "take_photo", "generate_image"]


def test_tool_steps_laya_required_prompt_tools_optional(registry):
    steps = registry.tool_steps(
        ["remember", "convert", "calculate", "search_memory", "take_photo", "nope"],
        ["remember", "convert", "calculate"])
    assert steps == [
        ("search_memory", False),
        ("convert", True),
        ("calculate", True),
        ("remember", False),
        ("take_photo", False),
    ]
    # spawn_job is mandatory only when laya detected it; search_memory and remember stay optional
    assert registry.tool_steps(["spawn_job", "search_memory", "remember"], ["spawn_job"]) == [
        ("search_memory", False), ("spawn_job", True), ("remember", False)]
    assert registry.tool_steps(["websearch"], []) == [("websearch", False)]


def test_hydrated_prompt_forces_only_laya_tools(registry):
    forced = registry.get_tools_hydrated(["convert"], ["convert"])
    assert "You must call it." in forced
    assert "Do not skip it." in forced
    assert "If it needs none, output nothing." not in forced
    assert "CONVERT:" in forced

    optional = registry.get_tools_hydrated(["search_memory", "remember", "take_photo"])
    assert "These tools are optional." in optional
    assert "Outputting nothing is the correct answer when the query needs none of them." in optional
    assert "MUST" not in optional
    assert "Write this call" not in optional
    assert "SEARCH MEMORY:" in optional and "REMEMBER:" in optional and "TAKE PHOTO:" in optional

    # passing a prompt tool as "detected" does not make it mandatory
    still_optional = registry.get_tools_hydrated(["remember"], ["remember"])
    assert "MUST" not in still_optional
    assert "These tools are optional." in still_optional

    mixed = registry.get_tools_hydrated(["convert", "calculate", "remember"], ["convert", "calculate", "remember"])
    assert "These tools were detected as necessary and must be called: convert, calculate." in mixed
    assert "For the other tools, call only those the query really needs." in mixed
    must_line = mixed.split("must be called: ", 1)[1].split(".", 1)[0]
    assert must_line == "convert, calculate"


def test_directing_query_carries_results_except_a_required_keep_call():
    calculate = directing_query("add the converted amount", ["calculate"], "SECRET_RESULT", required=True)
    assert "SECRET_RESULT" in calculate
    assert "RESULTS SO FAR" in calculate
    assert "query itself" not in calculate
    assert "Write this call" not in calculate

    first = directing_query("convert 10 USD", ["convert"], "", required=True)
    assert "RESULTS SO FAR" not in first
    assert "THE QUERY\nconvert 10 USD" in first

    optional = directing_query("I have 100 USD", ["search_memory", "remember", "take_photo"], "SECRET_RESULT")
    assert "SECRET_RESULT" in optional
    assert "Outputting nothing is the correct answer" in optional
    assert "Write this call" not in optional
    assert "MUST" not in optional

    spawn = directing_query("research this", ["spawn_job"], "SECRET_RESULT", required=True)
    assert "SECRET_RESULT" not in spawn
    assert "RESULTS SO FAR" not in spawn
    assert "Write this call from the query itself." in spawn


def test_sequence_is_strictly_serial_convert_before_calculate(registry):
    response = {"tool_results": []}
    events = []

    def results_text():
        return "\n".join(f"{item['tool']}: {item.get('text') or item.get('error')}" for item in response["tool_results"])

    def direct(name, required, results):
        events.append(("direct", name, required, results))
        if name == "search_memory":
            return {"content": "", "tool_calls": []}
        if name == "convert":
            # a stray calculate written in this request must not run before convert's own result
            return {"content": "", "tool_calls": [{"tool": "convert"}, {"tool": "calculate", "expression": "early"}]}
        if name == "calculate":
            return {"content": "", "tool_calls": [{"tool": "calculate", "expression": "1+1"}]}
        return None

    def direct_optional(names, results):
        events.append(("optional", list(names), results))
        return {"content": "", "tool_calls": []}

    def execute(calls):
        events.append(("execute", [call["tool"] for call in calls]))
        for call in calls:
            response["tool_results"].append({"tool": call["tool"], "text": call["tool"] + " done"})

    failures = []
    steps = registry.tool_steps(
        ["calculate", "convert", "search_memory", "remember", "take_photo"],
        ["convert", "calculate"])
    sync, parallel, interrupted = run_tool_sequence(
        steps, direct, execute, results_text, lambda name, error: failures.append((name, error)),
        lambda name: registry.parallel[name], direct_optional=direct_optional)
    if not interrupted:
        events.append("finalize")

    assert interrupted is False
    assert failures == []
    assert parallel == []
    assert [event[0] if isinstance(event, tuple) else event for event in events] == [
        "direct", "execute", "direct", "execute", "optional", "finalize"]
    assert [event[1] for event in events if isinstance(event, tuple) and event[0] == "direct"] == [
        "convert", "calculate"]
    assert [event[1] for event in events if isinstance(event, tuple) and event[0] == "execute"] == [
        ["convert"], ["calculate"]]
    assert events[-1] == "finalize"
    convert = next(event for event in events if event[0] == "direct" and event[1] == "convert")
    calculate = next(event for event in events if event[0] == "direct" and event[1] == "calculate")
    optional = next(event for event in events if event[0] == "optional")
    assert convert[2] is True and convert[3] == ""
    assert calculate[2] is True and "convert done" in calculate[3]
    assert optional[1] == ["search_memory", "remember", "take_photo"]
    assert "convert done" in optional[2] and "calculate done" in optional[2]
    assert events.index(convert) < events.index(("execute", ["convert"])) < events.index(calculate) < events.index(optional)
    assert sync == [{"tool": "convert"}, {"tool": "calculate", "expression": "1+1"}]


def test_mandatory_miss_records_failure_and_continues():
    response = {"tool_results": []}
    seen = []
    failures = []

    def direct(name, required, results):
        seen.append((name, required, results))
        if name == "convert":
            return None
        if name == "calculate":
            return {"tool_calls": []}
        return {"tool_calls": []}

    def execute(calls):
        raise AssertionError("nothing was callable")

    def on_failure(name, error):
        failures.append((name, error))
        response["tool_results"].append({"tool": name, "error": error})

    def results_text():
        return "\n".join(f"{item['tool']}: {item['error']}" for item in response["tool_results"])

    def direct_optional(names, results):
        seen.append(("optional", tuple(names), results))
        return {"tool_calls": []}

    steps = [("convert", True), ("calculate", True), ("remember", False)]
    sync, parallel, interrupted = run_tool_sequence(
        steps, direct, execute, results_text, on_failure, lambda name: False, direct_optional=direct_optional)
    assert interrupted is False
    assert sync == [] and parallel == []
    assert failures == [("convert", "tool directing failed"), ("calculate", "no call written")]
    assert [item[0] for item in seen] == ["convert", "calculate", "optional"]
    assert seen[2][1] == ("remember",)
    assert "convert: tool directing failed" in seen[1][2]
    assert "no call written" in seen[2][2]


def test_optional_skip_and_no_tools_and_parallel_deferred():
    calls = []
    failures = []

    def direct(name, required, results):
        raise AssertionError("optional tools are not asked one by one")

    def direct_optional(names, results):
        calls.append(tuple(names))
        return {"tool_calls": [{"tool": "take_photo", "who": "self"}]}

    executed = []
    sync, parallel, interrupted = run_tool_sequence(
        [("search_memory", False), ("take_photo", False)], direct,
        lambda found: executed.append(found), lambda: "", lambda name, error: failures.append((name, error)),
        lambda name: name == "take_photo", direct_optional=direct_optional)
    assert interrupted is False
    assert failures == []
    assert executed == []
    assert sync == []
    assert parallel == [{"tool": "take_photo", "who": "self"}]
    assert calls == [("search_memory", "take_photo")]

    calls.clear()

    def empty_optional(names, results):
        calls.append(tuple(names))
        return {"tool_calls": []}

    sync, parallel, interrupted = run_tool_sequence(
        [("search_memory", False), ("remember", False), ("take_photo", False)], direct,
        lambda found: pytest.fail("ran"), lambda: "done", lambda name, error: pytest.fail(error),
        lambda name: False, direct_optional=empty_optional)
    assert (sync, parallel, interrupted) == ([], [], False)
    assert calls == [("search_memory", "remember", "take_photo")]

    directed = []
    sync, parallel, interrupted = run_tool_sequence(
        [], lambda *args: directed.append(args), lambda calls: pytest.fail("ran"),
        lambda: "", lambda name, error: pytest.fail(error), lambda name: False)
    assert (sync, parallel, interrupted, directed) == ([], [], False, [])


def test_interrupted_sequence_does_not_finalize():
    events = []
    stop = {"after": False}

    def direct(name, required, results):
        events.append(("direct", name))
        return {"tool_calls": [{"tool": name}]}

    def execute(calls):
        events.append(("execute", calls[0]["tool"]))
        stop["after"] = True

    def direct_optional(names, results):
        events.append(("optional", list(names)))

    sync, parallel, interrupted = run_tool_sequence(
        [("convert", True), ("calculate", True), ("remember", False)], direct, execute, lambda: "so far",
        lambda name, error: pytest.fail(error), lambda name: False, interrupted=lambda: stop["after"],
        direct_optional=direct_optional)
    if not interrupted:
        events.append("finalize")
    assert interrupted is True
    assert sync == [{"tool": "convert"}]
    assert parallel == []
    assert events == [("direct", "convert"), ("execute", "convert")]


def test_directing_task_forces_laya_tool_and_passes_results(registry):
    class DB:
        def get_contact_by_id(self, contact_id):
            return {}

        def get_conversation(self, conversation_id):
            return {}

    class Infra:
        def __init__(self):
            self.messages = None

        def chat(self, messages, temperature, seed):
            self.messages = messages
            return '{"tool": "calculate", "expression": "1+1"}'

    infra = Infra()
    request = ChatRequest(contact_id=1, conversation_id=2, role="user", name="Sam",
                          content="add the converted price", temperature=0.3)
    task = ToolDirectingTask(request, DB(), infra, registry, ["calculate"],
                             results="SECRET_RESULT", detected_tool_names=["calculate"])
    task.execute()
    assert "You must call it." in infra.messages[0]["content"]
    assert "CALCULATE:" in infra.messages[0]["content"]
    assert "SECRET_RESULT" in infra.messages[-1]["content"]
    assert task.result()["tool_calls"] == [{"tool": "calculate", "expression": "1+1"}]

    class Down:
        def chat(self, messages, temperature, seed):
            raise RuntimeError("llm down")

    failed = ToolDirectingTask(request, DB(), Down(), registry, ["calculate"], detected_tool_names=["calculate"])
    failed.execute()
    assert failed.result() is None

    optional_infra = Infra()
    optional = ToolDirectingTask(request, DB(), optional_infra, registry,
                                 ["search_memory", "remember", "take_photo"], results="SECRET_RESULT")
    optional_infra.chat = lambda messages, temperature, seed: (setattr(optional_infra, "messages", messages) or "")
    optional.execute()
    assert "These tools are optional." in optional_infra.messages[0]["content"]
    assert "Outputting nothing is the correct answer when the query needs none of them." in optional_infra.messages[0]["content"]
    assert "MUST" not in optional_infra.messages[0]["content"]
    assert "Write this call" not in optional_infra.messages[-1]["content"]
    assert "MUST" not in optional_infra.messages[-1]["content"]
    assert "SECRET_RESULT" in optional_infra.messages[-1]["content"]
    assert optional.result()["tool_calls"] == []


def _install_turn_fakes(monkeypatch, events, detected, answer):
    class ScriptedDetection(Task):
        def __init__(self, prompt, tool_registry, infrastructure, excluded=()):
            super().__init__()
            self.tool_names = list(detected)

        def execute(self):
            return None

        def result(self):
            return self.tool_names

    class ScriptedDirecting(Task):
        def __init__(self, request, db, infrastructure, tool_registry, tool_names, results="", detected_tool_names=None):
            super().__init__()
            self.tool_names = list(tool_names)
            self.results = results or ""
            self.detected_tool_names = list(detected_tool_names or [])
            self.tool_response = None
            events.append(("direct", self.tool_names, self.results, self.detected_tool_names))

        def execute(self):
            key = self.tool_names[0] if len(self.tool_names) == 1 else tuple(self.tool_names)
            self.tool_response = answer(key, self.results, self.detected_tool_names)

        def result(self):
            return self.tool_response

    def chat_execute(self):
        events.append(("chat", self.thinking_response))
        self.callback(json.dumps({"response": "answer"}))

    monkeypatch.setattr("app.tasks.meta_task.ToolDetectionTask", ScriptedDetection)
    monkeypatch.setattr("app.tasks.meta_task.ToolDirectingTask", ScriptedDirecting)
    monkeypatch.setattr("app.tasks.meta_task.ChatTask.execute", chat_execute)

    original = MessageQueue.send_status_message

    def send(self, message, *args, **kwargs):
        events.append(("status", message))
        return original(self, message, *args, **kwargs)

    monkeypatch.setattr(MessageQueue, "send_status_message", send)


def _run_turn(monkeypatch, detected, answer):
    events = []
    _install_turn_fakes(monkeypatch, events, detected, answer)

    class DB:
        def __init__(self):
            self.tools = None

        def get_message_count_by_conversation(self, conversation_id):
            return 2

        def get_contact_by_id(self, contact_id):
            return {"identity": {"name": "Ada"}, "profile": {}}

        def add_message(self, conversation_id, role, content, name):
            return 11

        def set_message_tools(self, message_id, tools):
            self.tools = tools

    class Turns:
        def set_state(self, job, state):
            events.append(("state", state))
            return True

    db = DB()
    registry = ToolRegistry(None, None, None)

    def execute(user_id, contact_id, conversation_id, response, tool_calls, parallel=False):
        events.append(("run", [call["tool"] for call in tool_calls], parallel))
        if parallel:
            return
        for call in tool_calls:
            response.setdefault("tool_results", []).append({"tool": call["tool"], "text": call["tool"] + " done"})

    registry.execute = execute
    queue = TaskQueue(max_parallel=2)
    try:
        meta = MetaTask(
            user_id=1,
            request=ChatRequest(contact_id=1, conversation_id=2, role="user", name="Sam",
                                content="convert 10 USD to EUR and add 5", temperature=0.3),
            db=db, infrastructure=object(), tool_registry=registry, turns=Turns())
        meta._update_conversation_context = lambda: events.append("context")
        queue.run(meta)
    finally:
        queue.stop()
    return events, db


def _directs(events):
    return [event for event in events if isinstance(event, tuple) and event[0] == "direct"]


def _sync_runs(events):
    return [event for event in events if isinstance(event, tuple) and event[0] == "run" and event[2] is False]


def _assert_finalized_after_sequence(events):
    finalize = next(i for i, event in enumerate(events) if event == ("status", "finalize answer"))
    compile_at = next(i for i, event in enumerate(events) if event == ("status", "compile response"))
    chat = next(i for i, event in enumerate(events) if isinstance(event, tuple) and event[0] == "chat")
    last_direct = max(i for i, event in enumerate(events) if isinstance(event, tuple) and event[0] == "direct")
    assert compile_at > last_direct
    assert finalize > compile_at
    assert chat > finalize
    assert events[chat][1]


def test_meta_task_asks_in_order_and_finalizes_after(monkeypatch):
    def answer(name, results, detected_names):
        if name in ("convert", "calculate"):
            return {"content": "", "tool_calls": [{"tool": name}]}
        return {"content": "", "tool_calls": []}

    events, db = _run_turn(monkeypatch, ["convert", "calculate"], answer)
    directs = _directs(events)
    assert [event[1] for event in directs] == [
        ["convert"], ["calculate"], ["search_memory", "remember", "take_photo"]]
    by_name = {event[1][0]: event for event in directs if len(event[1]) == 1}
    assert by_name["convert"][3] == ["convert"] and by_name["convert"][2] == ""
    assert by_name["calculate"][3] == ["calculate"] and "convert done" in by_name["calculate"][2]
    optional = directs[-1]
    assert optional[3] == []
    assert "calculate done" in optional[2]
    assert [event[1] for event in _sync_runs(events)] == [["convert"], ["calculate"]]
    assert events.index(by_name["convert"]) < events.index(("run", ["convert"], False)) < events.index(by_name["calculate"]) < events.index(optional)
    _assert_finalized_after_sequence(events)
    assert "convert done" in events[next(i for i, event in enumerate(events) if isinstance(event, tuple) and event[0] == "chat")][1]
    assert db.tools == ["convert", "calculate"]


def test_meta_task_no_detected_tools_still_finalizes(monkeypatch):
    events, db = _run_turn(monkeypatch, [], lambda name, results, detected: {"content": "", "tool_calls": []})
    assert [event[1] for event in _directs(events)] == [["search_memory", "remember", "take_photo"]]
    assert _sync_runs(events) == []
    assert _directs(events)[0][3] == []
    _assert_finalized_after_sequence(events)
    chat = next(event for event in events if isinstance(event, tuple) and event[0] == "chat")
    assert "No web search was done" in chat[1]
    assert "failed -" not in chat[1]
    assert db.tools is None


def test_meta_task_mandatory_miss_continues_then_finalizes(monkeypatch):
    def answer(name, results, detected_names):
        if name == "calculate":
            return {"content": "", "tool_calls": [{"tool": "calculate", "expression": "1"}]}
        return {"content": "", "tool_calls": []}

    events, db = _run_turn(monkeypatch, ["convert", "calculate"], answer)
    by_name = {event[1][0]: event for event in _directs(events)}
    assert "convert: tool directing failed" not in by_name["calculate"][2]
    assert "no call written" in by_name["calculate"][2]
    assert [event[1] for event in _sync_runs(events)] == [["calculate"]]
    _assert_finalized_after_sequence(events)
    chat = next(event for event in events if isinstance(event, tuple) and event[0] == "chat")
    assert "convert: failed - no call written" in chat[1]
    assert "calculate done" in chat[1]
    assert db.tools == ["calculate"]


def _agent(detected, answer):
    events = []

    class InlineQueue:
        def run(self, job):
            job.execute()

    class FakeDetection:
        def __init__(self, prompt, tool_registry, infrastructure, excluded=()):
            self.names = list(detected)

        def execute(self):
            self.tool_names = self.names

        def result(self):
            return self.tool_names

    class FakeDirecting:
        def __init__(self, request, db, infrastructure, tool_registry, tool_names, results="", detected_tool_names=None):
            self.tool_names = list(tool_names)
            self.results = results or ""
            self.detected_tool_names = detected_tool_names
            self.tool_response = None
            events.append(("direct", self.tool_names, self.results, self.detected_tool_names))

        def execute(self):
            key = self.tool_names[0] if len(self.tool_names) == 1 else tuple(self.tool_names)
            self.tool_response = answer(key, self.results, self.detected_tool_names)

        def result(self):
            return self.tool_response

    registry = ToolRegistry(None, None, InlineQueue())

    def execute(user_id, contact_id, conversation_id, response, tool_calls, parallel=False):
        events.append(("run", [call["tool"] for call in tool_calls]))
        for call in tool_calls:
            response.setdefault("tool_results", []).append({"tool": call["tool"], "text": call["tool"] + " done"})

    registry.execute = execute
    job = AgentJob(role="researcher", prompt="convert 10 USD to EUR and add 5", infrastructure=object(), tool_context={
        "tool_registry": registry, "db": object(), "user_id": 1, "contact_id": 2, "conversation_id": 3, "user_name": "Sam"})
    return job, events, FakeDetection, FakeDirecting


def test_worker_asks_in_order_and_keeps_always_tools_optional(monkeypatch):
    def answer(name, results, detected_names):
        if name in ("convert", "calculate"):
            return {"content": "", "tool_calls": [{"tool": name}]}
        return {"content": "", "tool_calls": []}

    job, events, detection, directing = _agent(["convert", "calculate"], answer)
    monkeypatch.setattr("app.tasks.ToolDetectionTask", detection)
    monkeypatch.setattr("app.tasks.ToolDirectingTask", directing)
    directed = job.find_tools("convert 10 USD to EUR and add 5", "convert 10 USD to EUR and add 5", ["websearch"])
    directs = _directs(events)
    assert [event[1] for event in directs] == [["convert"], ["calculate"], ["search_memory", "websearch"]]
    by_name = {event[1][0]: event for event in directs if len(event[1]) == 1}
    optional = directs[-1]
    assert optional[3] is None
    assert "remember" not in optional[1] and "take_photo" not in optional[1]
    assert by_name["convert"][3] == ["convert"]
    assert by_name["calculate"][3] == ["calculate"]
    assert by_name["convert"][2] == ""
    assert "convert done" in by_name["calculate"][2]
    assert "calculate done" in optional[2]
    runs = [event for event in events if event[0] == "run"]
    assert [event[1] for event in runs] == [["convert"], ["calculate"]]
    assert events.index(by_name["convert"]) < events.index(("run", ["convert"])) < events.index(by_name["calculate"]) < events.index(optional)
    assert [call["tool"] for call in directed["tool_calls"]] == ["convert", "calculate"]


def test_worker_mandatory_miss_is_a_tool_error_after_the_rest_ran(monkeypatch):
    def answer(name, results, detected_names):
        if name == "convert":
            return {"content": "", "tool_calls": [{"tool": "convert"}]}
        if name == "calculate":
            return None
        return {"content": "", "tool_calls": []}

    job, events, detection, directing = _agent(["convert", "calculate"], answer)
    monkeypatch.setattr("app.tasks.ToolDetectionTask", detection)
    monkeypatch.setattr("app.tasks.ToolDirectingTask", directing)
    directed = job.find_tools("q", "q", ["websearch"])
    assert directed is not None
    assert [call["tool"] for call in directed["tool_calls"]] == ["convert"]
    assert {"tool": "calculate", "error": "tool directing failed"} in job.response["tool_results"]
    assert "calculate" in {event[1][0] for event in _directs(events)}


def test_worker_directing_down_returns_none(monkeypatch):
    job, events, detection, directing = _agent(["convert"], lambda name, results, detected: None)
    monkeypatch.setattr("app.tasks.ToolDetectionTask", detection)
    monkeypatch.setattr("app.tasks.ToolDirectingTask", directing)
    assert job.find_tools("q", "q", []) is None
    assert any(event[0] == "direct" and event[1] == ["convert"] for event in events)
