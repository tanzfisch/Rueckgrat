import re
from .task_queue import Task
from typing import List, Optional, Dict, Any, Tuple

from app.common import get_logger, Utils
from app.utils.trace import Trace
logger = get_logger()

MANDATORY_THRESHOLD = 0.7
RECOMMENDED_THRESHOLD = 0.5
MIN_DETECTION_WORDS = 4    # shorter messages ("Hi", "thanks!") skip the laya questions, they scored spawn_job 0.71 on "Hi"
PROJECT_KEY = "project"    # the ids of the ToolRegistry.PROJECT_QUESTIONS: "project__<i>"

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
    def __init__(self, prompt: str, tool_registry, infrastructure, excluded_tools: tuple = (), volume=None):
        """volume: the conversation's files (ConversationVolume), the PROJECT_QUESTIONS are asked. None: they are not"""
        super().__init__()
        self.prompt = prompt
        self.excluded_tools = excluded_tools
        self.volume = volume
        self.project = None     # whether the files hold a project, None: not checked (no project question scored high enough)
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.tool_names = None
        self.recommended = []
        self.scores = {}    # question id -> (its score, the question), for the trace

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

        if self.volume is not None and self.tool_registry.project_tools(self.excluded_tools):
            for i, question in enumerate(self.tool_registry.PROJECT_QUESTIONS):
                questions[f"{PROJECT_KEY}__{i}"] = {"type": "noul", "instructions": question}

        return questions

    def thresholds(self, name: str) -> Tuple[float, float]:
        """the (recommended, mandatory) thresholds of a tool: its own (Tool.thresholds) or the global ones"""
        cls = self.tool_registry.tools.get(name)
        return getattr(cls, "thresholds", None) or (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD)

    def _has_project(self) -> bool:
        """whether the conversation's files hold a project (ConversationVolume.has_project), False when they can't be read"""
        try:
            self.project = self.volume.has_project()
        except Exception as e:
            logger.error(f"files of the conversation not checked for a project {repr(e)}")
            self.project = False
        return self.project

    def _check_fetch_url(self) -> Optional[str]:
        if "fetch_url" in self.excluded_tools:
            return None
        if URL_PATTERN.search(self.prompt or ""):
            return "fetch_url"
        return None

    def _detect(self) -> Optional[List[str]]:
        url_check = self._check_fetch_url()        

        if len(self.prompt.split()) < MIN_DETECTION_WORDS:
            logger.debug(f"tool detection skipped, fewer than {MIN_DETECTION_WORDS} words")
            return self.tool_registry.bands([url_check] if url_check else [], [])

        questions = self._questions()
        answers = self.infrastructure.decide(self.prompt, questions)
        if answers is None:
            return ([url_check] if url_check else None), []    # a link still selects fetch_url when laya is down; otherwise the caller falls back

        probabilities = {}
        for key, answer in answers.items():
            name = key.rsplit("__", 1)[0]
            if name == "fetch_url":
                continue
            probabilities[name] = max(probabilities.get(name, 0.0), answer.get("noul", 0.0))
            self.scores[key] = (answer.get("noul", 0.0), questions.get(key, {}).get("instructions", ""))

        # a fix or change of what was made earlier selects the PROJECT_TOOLS, only when there is a project to change
        project = probabilities.pop(PROJECT_KEY, 0.0)
        if project >= RECOMMENDED_THRESHOLD and self._has_project():
            for name in self.tool_registry.project_tools(self.excluded_tools):
                probabilities[name] = max(probabilities.get(name, 0.0), project)
        
        tool_names = [name for name, p in probabilities.items() if p >= self.thresholds(name)[1]]
        recommended = [name for name, p in probabilities.items() if self.thresholds(name)[0] <= p < self.thresholds(name)[1]]

        probabilities["fetch_url"] = 1.0 if url_check else 0.0
        logger.debug(f"tool probabilities:\n{Utils.pretty_scores(probabilities, 20, (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD))}")

        # add fetch_url if detected
        if url_check:
            tool_names.append(url_check)

        return self.tool_registry.bands(tool_names, recommended)

    def trace(self, conversation_id: int, who: str) -> None:
        """the detection into the decision trace: the text it judged, each question's score and what it chose"""
        lines = [f"{score:.4f}  {key}  {question}" for key, (score, question) in sorted(self.scores.items(), key=lambda item: -item[1][0])]
        Trace.write(conversation_id, f"tool detection, {who}", f"TEXT:\n{self.prompt}\nSCORES (per question, best first):\n" + "\n".join(lines),
                    mandatory=self.tool_names, recommended=self.recommended, thresholds=[RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD],
                    excluded=list(self.excluded_tools), project_files=self.project)
