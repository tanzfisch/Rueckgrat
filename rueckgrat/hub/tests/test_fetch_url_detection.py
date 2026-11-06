"""fetch_url comes from URL_PATTERN, not from a laya question. no network and no model calls."""
from app.tasks.tool_detection_task import ToolDetectionTask, URL_PATTERN

ADDRESS = "correct.\nbtw. I just moved and my new address is 100 Riverbank Road RD7 Palmerston North 4477"
ADDRESS_BLANK_LINE = "correct.\n\nbtw. I just moved and my new address is 100 Riverbank Road RD7 Palmerston North 4477"


class _Tool:
    def __init__(self, question):
        self.question = question
        self.description = "a tool"


class _Registry:
    PROMPT_TOOLS = ["remember", "search_memory", "take_photo"]
    tools = {
        "calculate": _Tool(["Does the user ask for arithmetic?"]),
        "show_map": _Tool(["Does the user mention a place?"]),
        "fetch_url": _Tool([]),
        "remember": _Tool([]),
    }


class _Decisions:
    def __init__(self, answers):
        self.answers = answers
        self.questions = None
        self.state = None

    def decide(self, state, questions):
        self.state = state
        self.questions = questions
        return self.answers


def _detect(text, answers):
    decisions = _Decisions(answers)
    task = ToolDetectionTask(text, _Registry(), decisions)
    found = task._detect()
    return found, decisions


def test_pattern_accepts_scheme_www_and_known_tld():
    assert URL_PATTERN.search("see https://example.com/article")
    assert URL_PATTERN.search("http://example.com")
    assert URL_PATTERN.search("look at www.example.com/path")
    assert URL_PATTERN.search("the post is on reddit.com/r/maps")
    assert URL_PATTERN.search("nzherald.co.nz/story")


def test_address_message_is_not_a_url():
    assert URL_PATTERN.search(ADDRESS) is None
    assert URL_PATTERN.search(ADDRESS_BLANK_LINE) is None
    assert URL_PATTERN.search("correct.btw") is None
    assert URL_PATTERN.search("RD7 Palmerston North 4477") is None


def test_url_selects_fetch_url_and_laya_is_not_asked():
    found, decisions = _detect("please read https://example.com/article and add 2+2", {
        "calculate__0": {"noul": 0.9},
        "show_map__0": {"noul": 0.1},
        "fetch_url__0": {"noul": 0.99},
    })
    assert found == ["calculate", "fetch_url"]
    assert decisions.state.startswith("please read https://")
    assert all(not key.startswith("fetch_url") for key in decisions.questions)
    assert "remember" not in decisions.questions


def test_address_does_not_select_fetch_url_even_if_laya_would():
    found, decisions = _detect(ADDRESS, {
        "calculate__0": {"noul": 0.1},
        "show_map__0": {"noul": 0.88},
        "fetch_url__0": {"noul": 0.99},
    })
    assert found == ["show_map"]
    assert all(not key.startswith("fetch_url") for key in decisions.questions)


def test_no_url_and_no_laya_falls_back():
    found, _ = _detect("hello there", None)
    assert found is None


def test_url_is_kept_when_laya_is_down():
    found, _ = _detect("see www.example.com", None)
    assert found == ["fetch_url"]
