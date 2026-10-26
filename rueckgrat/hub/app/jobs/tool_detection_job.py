from .job_queue import Job
from typing import List, Optional

from app.common import get_logger
logger = get_logger()

MAX_QUESTIONS = 64      # the node's limit per request, one question per tool
TOOL_THRESHOLD = 0.3    # a tool is needed above this P(true). a guess: the base model needs tuning or fine-tuning on own data
EXCLUSIVE_TOOLS = [                  # only the more likely tool of each group is kept
    ("generate_image", "take_photo")  # we reply with one image at a time
]


class ToolDetectionJob(Job):
    """detects all tools a prompt needs with the decision node (laya), one yes/no question per registered tool, one forward pass.
    result(): the needed tool names (may be empty), or None if decisions are not available, the caller falls back then"""
    def __init__(self, prompt: str, tool_registry, infrastructure):
        super().__init__()
        self.prompt = prompt
        self.tool_registry = tool_registry
        self.infrastructure = infrastructure
        self.tool_names = None

    def execute(self) -> None:
        try:
            self.tool_names = self._detect()
        except Exception as e:
            logger.error(f"failed to detect tools {repr(e)}")

    def result(self) -> Optional[List[str]]:
        return self.tool_names

    def _questions(self) -> dict:
        questions = {}
        for name, cls in self.tool_registry.tools.items():
            if name in self.tool_registry.PROMPT_TOOLS:   # not detected, always in the tool directing prompt
                continue
            question = cls.question or f"Does answering the user's latest message need the tool '{name}': {cls.get_description()}?"
            questions[name] = {
                "type": "noul",
                "instructions": question
            }
        if len(questions) > MAX_QUESTIONS:
            logger.warning(f"{len(questions)} tools, only the first {MAX_QUESTIONS} are checked")
            questions = dict(list(questions.items())[:MAX_QUESTIONS])
        return questions

    def _detect(self) -> Optional[List[str]]:
        if not (self.prompt or "").strip():
            return []
        answers = self.infrastructure.decide(self.prompt, self._questions())
        if answers is None:
            return None

        probabilities = {name: answer.get("noul", 0.0) for name, answer in answers.items()}
        logger.debug(f"tool probabilities: {probabilities}")
        tool_names = [name for name, p in probabilities.items() if p >= TOOL_THRESHOLD]

        for group in EXCLUSIVE_TOOLS:
            selected = [name for name in tool_names if name in group]
            if len(selected) > 1:
                keep = max(selected, key=lambda name: probabilities[name])
                tool_names = [name for name in tool_names if name not in group or name == keep]
        return tool_names
