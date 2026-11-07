import re
from .task_queue import Task
from typing import List, Optional, Dict, Any

from app.common import get_logger, Utils
logger = get_logger()

MAX_QUESTIONS = 64
MANDATORY_THRESHOLD = 0.7
RECOMMENDED_THRESHOLD = 0.4

# fetch_url is not a laya question but a regex to look for URLs
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
    """detecting possible tools requests so we can offer the tools to the AI to use"""
    def __init__(self, prompt: str, tool_registry, infrastructure, excluded_tools: tuple = ()):
        super().__init__()
        self.prompt = prompt
        self.excluded_tools = excluded_tools
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.tool_names = None
        self.recommended = []

    def execute(self) -> None:
        try:
            if not (self.prompt or "").strip():
                return
                        
            self.tool_names, self.recommended = self._detect()
        except Exception as e:
            logger.error(f"failed to detect tools {repr(e)}")

    def get_result(self) -> Dict[str, Any]:
        """tool_names must be called, recommended the model decides about (see ToolRegistry.bands)"""
        return {
            "tool_names": self.tool_names,
            "recommended": self.recommended
        }

    def _questions(self) -> dict:
        """one laya question per id "<tool>__<i>", a tool without questions gets one from its description"""
        questions = {}
        for name, cls in self.tool_registry.tools.items():
            if name in self.tool_registry.PROMPT_TOOLS or name in self.excluded_tools or name == "fetch_url":
                continue

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

    def _check_fetch_url(self) -> Optional[str]:
        if "fetch_url" in self.excluded_tools:
            return None
        if URL_PATTERN.search(self.prompt or ""):
            return "fetch_url"
        return None

    def _detect(self) -> Optional[List[str]]:
        url_check = self._check_fetch_url()        

        answers = self.infrastructure.decide(self.prompt, self._questions())
        if answers is None:
            return ([url_check] if url_check else None), []    # a link still selects fetch_url when laya is down; otherwise the caller falls back

        probabilities = {}
        for key, answer in answers.items():
            name = key.rsplit("__", 1)[0]
            if name == "fetch_url":
                continue
            probabilities[name] = max(probabilities.get(name, 0.0), answer.get("noul", 0.0))
        
        tool_names = [name for name, p in probabilities.items() if p >= MANDATORY_THRESHOLD]
        recommended = [name for name, p in probabilities.items() if RECOMMENDED_THRESHOLD <= p < MANDATORY_THRESHOLD]

        probabilities["fetch_url"] = 1.0 if url_check else 0.0
        logger.debug(f"tool probabilities:\n{Utils.pretty_scores(probabilities, 20, (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD))}")

        # add fetch_url if detected
        if url_check:
            tool_names.append(url_check)

        return self.tool_registry.bands(tool_names, recommended)
