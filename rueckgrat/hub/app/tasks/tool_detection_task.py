import re
from .task_queue import Task
from typing import List, Optional

from app.common import get_logger, Utils
logger = get_logger()

MAX_QUESTIONS = 64      # the node's limit per request, a tool may have several questions
TOOL_THRESHOLD = 0.5    # a tool is needed above this P(true). a guess: the base model needs tuning or fine-tuning on own data
EXCLUSIVE_TOOLS = [                  # only the more likely tool of each group is kept
    ("generate_image", "take_photo")  # we reply with one image at a time
]
# when spawn_job is detected it is the only detected tool: the agents do the work (search, code, ...), other tools on the
# same message (e.g. run_code) would start a second, half done answer to it. PROMPT_TOOLS are added after and stay
PRIORITY_TOOL = "spawn_job"
# fetch_url is not a laya question. a link in the message selects it. a bare host needs a known TLD or a
# two-letter code; file extensions that are also ccTLDs (main.py, README.md, run.sh) don't count.
# emails, versions and decimals don't match. "correct.btw" does not: btw is not a listed TLD and not two letters
TLDS = r"com|org|net|edu|gov|mil|int|info|biz|io|ai|app|dev|xyz|online|site|tech|blog|news|shop|store|cloud|page|link|live|media|tv"
NOT_TLDS = r"py|md|sh|rs|pl|cc|cs|so|ps|hs|ml|mk|tf|pm|gz|js|ts|rb|kt|go|db"
URL_PATTERN = re.compile(rf"""
    [a-z][a-z0-9+.-]*://\S+                                   # any scheme, also glued to a word: protestshttps://...
  | \bwww\.[\w-]+\.\S+                                       # www.example.org
  | \blocalhost(?::\d+|/)\S*                                 # localhost:8080, localhost/x
  | (?<![\w.])(?:\d{{1,3}}\.){{3}}\d{{1,3}}(?!\.?\d)(?::\d+)?(?:/\S*)?   # 192.168.2.39:7346/x
  | (?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+       # bare host: reddit.com, nzherald.co.nz, bit.ly/x
      (?:{TLDS}|(?!(?:{NOT_TLDS})(?![\w-]))[a-z]{{2}})(?![\w-])
""", re.IGNORECASE | re.VERBOSE)


class ToolDetectionTask(Task):
    """detects all tools a prompt needs with the decision node (laya), yes/no questions per registered tool, one forward pass.
    result(): the needed tool names (may be empty), or None if decisions are not available, the caller falls back then"""
    def __init__(self, prompt: str, tool_registry, infrastructure, excluded: tuple = ()):
        super().__init__()
        self.prompt = prompt
        self.excluded = excluded    # tools not asked about (workers: WORKER_EXCLUDED_TOOLS, they never get spawn_job)
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
        """one laya question per id "<tool>__<i>", a tool without questions gets one from its description"""
        questions = {}
        for name, cls in self.tool_registry.tools.items():
            if name in self.tool_registry.PROMPT_TOOLS or name in self.excluded or name == "fetch_url":
                continue    # PROMPT_TOOLS stay optional. fetch_url is URL_PATTERN, never a laya score
            tool_questions = cls.question or [f"Does answering the user's latest message need the tool '{name}': {cls.get_description()}?"]
            for i, question in enumerate(tool_questions):
                questions[f"{name}__{i}"] = {
                    "type": "noul",
                    "instructions": question
                }
        if len(questions) > MAX_QUESTIONS:
            logger.warning(f"{len(questions)} questions, only the first {MAX_QUESTIONS} are checked")
            questions = dict(list(questions.items())[:MAX_QUESTIONS])
        return questions

    def _linked_tools(self) -> List[str]:
        """fetch_url when the message itself has a url. laya is not asked"""
        if "fetch_url" in self.excluded or "fetch_url" not in self.tool_registry.tools:
            return []
        if URL_PATTERN.search(self.prompt or ""):
            return ["fetch_url"]
        return []

    def _detect(self) -> Optional[List[str]]:
        linked = self._linked_tools()
        if not (self.prompt or "").strip():
            return []
        answers = self.infrastructure.decide(self.prompt, self._questions())
        if answers is None:
            return linked or None    # a link still selects fetch_url when laya is down; otherwise the caller falls back

        probabilities = {}    # a tool counts with its most likely question. fetch_url is never one of these
        for key, answer in answers.items():
            name = key.rsplit("__", 1)[0]
            if name == "fetch_url":
                continue
            probabilities[name] = max(probabilities.get(name, 0.0), answer.get("noul", 0.0))

        logger.debug(f"tool probabilities:\n{Utils.pretty_scores(probabilities)}")
        tool_names = [name for name, p in probabilities.items() if p >= TOOL_THRESHOLD]

        for group in EXCLUSIVE_TOOLS:
            selected = [name for name in tool_names if name in group]
            if len(selected) > 1:
                keep = max(selected, key=lambda name: probabilities[name])
                tool_names = [name for name in tool_names if name not in group or name == keep]
        for name in linked:
            if name not in tool_names:
                tool_names.append(name)
        if PRIORITY_TOOL in tool_names:
            tool_names = [PRIORITY_TOOL]
        return tool_names
