import re

# English word lists: the shape of a message as a whole, without a model (#197, t463: measured on laya_tune/dataset.jsonl)
LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s*\S", re.MULTILINE)
SEQUENCE = re.compile(r"\b(?:first(?:ly)?|then|after that|afterwards|next|finally|lastly|at the end|in the end"
                      r"|once (?:done|that is done)|and then)\b", re.IGNORECASE)
WORK_KINDS = {      # kinds of work a message asks for, a job asks for several
    "research": r"research|look (?:\w+ )?up|find out|search|go through|investigate|do the research|market research",
    "find": r"find|collect|gather|pick|compare",
    "write": r"write|draft|compose|summari[sz]e|create a structure|outline",
    "build": r"build|code|program|develop|implement|set up",
    "make": r"create|make|design|generate|plan",
    "convert": r"turn (?:\w+ ){0,4}into|convert|read (?:\w+ ){0,3}into|narrate|record",
    "deliver": r"save|put (?:\w+ ){0,4}(?:in|into)|give me|send|download|export|spawn",
}
DELIVERABLES = {    # kinds of things a message asks to get
    "file": r"files?|document|markdown|csv|pdf|word|table|spreadsheet",
    "audio": r"audio(?:\s?book)?|audiobook|mp3|podcast|recording",
    "long": r"book|novel|chapters?|report|guide|newsletter|itinerary|business plan|script|essay",
    "code": r"app|game|website|api|backend|database|program|project",
    "link": r"download link|link",
}
WORK_PATTERNS = {kind: re.compile(rf"\b(?:{words})\b", re.IGNORECASE) for kind, words in WORK_KINDS.items()}
DELIVERABLE_PATTERNS = {kind: re.compile(rf"\b(?:{words})\b", re.IGNORECASE) for kind, words in DELIVERABLES.items()}
IMPERATIVE = re.compile(r"(?:^|[.!?:;\n]\s*|\b(?:and|then|please)\s+)(?:" + "|".join(WORK_KINDS.values()) + r")\b", re.IGNORECASE)
QUESTION_END = re.compile(r"\?\s*$")


class MessageShape:
    """the shape of a whole message, counted in code: the steps it lists, the kinds of work and deliverables it asks for,
    its imperatives and sequence words. complexity() tells a job of several steps (research, write, turn into audio, give
    the link) from a long but simple message (a story, a pasted email, a long question)"""

    def __init__(self, text: str):
        text = text or ""
        self._words = len(text.split())
        self._steps = len(LIST_ITEM.findall(text))
        self._sequence_words = len(SEQUENCE.findall(text))
        self._work_kinds = frozenset(kind for kind, pattern in WORK_PATTERNS.items() if pattern.search(text))
        self._imperatives = len(IMPERATIVE.findall(text))
        self._deliverables = frozenset(kind for kind, pattern in DELIVERABLE_PATTERNS.items() if pattern.search(text))
        self._asks_question = bool(QUESTION_END.search(text.strip()))

    def words(self) -> int:
        return self._words

    def steps(self) -> int:
        """the numbered and bulleted lines"""
        return self._steps

    def sequence_words(self) -> int:
        """first, then, after that, finally ..."""
        return self._sequence_words

    def work_kinds(self) -> frozenset:
        """the kinds of work asked for: research, find, write, build, make, convert, deliver"""
        return self._work_kinds

    def imperatives(self) -> int:
        """clauses that start with a work verb"""
        return self._imperatives

    def deliverables(self) -> frozenset:
        """the kinds of things asked for: file, audio, long (a book, a report ...), code, link"""
        return self._deliverables

    def asks_question(self) -> bool:
        """the message ends with a question: it asks rather than orders"""
        return self._asks_question

    def complexity(self) -> float:
        """0..1, how much of a job of several steps the message describes. jobs scored 0.31-1.0, long but simple messages
        at most 0.31 (t463)"""
        kinds = len(self._work_kinds)
        score = 0.25 * min(kinds, 4) / 4 * (2 if kinds >= 3 else 1)
        score += 0.15 * min(self._imperatives, 3) / 3
        score += 0.15 * min(len(self._deliverables), 3) / 3
        score += 0.10 * min(self._sequence_words, 2) / 2
        score += 0.10 * min(self._steps, 3) / 3
        score += 0.10 * min(self._words, 80) / 80
        if self._asks_question:
            score -= 0.25
        return round(max(0.0, min(1.0, score)), 3)
