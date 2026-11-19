from .task_queue import Task
from . import prompts
from typing import List, Optional, Dict, Any, Tuple

from app.common import get_logger, Utils
from app.utils.trace import Trace
logger = get_logger()

MANDATORY_THRESHOLD = 0.7
RECOMMENDED_THRESHOLD = 0.5
MIN_DETECTION_WORDS = 4    # shorter messages ("Hi", "thanks!") skip the laya questions, they scored spawn_job 0.71 on "Hi"
PROJECT_KEY = "project"    # the ids of the ToolRegistry.PROJECT_QUESTIONS: "project__<i>"
WHOLE_SUFFIX = " (whole)"  # a question's score on the whole message in the trace, the plain id is its best part
TEXT_SUFFIX = "__text"     # a tool's Tool.text_score in the trace
LLM_SUFFIX = "__llm"       # a tool the llm picked without laya in the trace (_pick)
PICK_MAX_TOKENS = 200      # the llm's pick without laya: {"tools": [...]} of a few names
PICK_TIMEOUT = 120         # seconds for that llm call
PICK_TEXT_CHARS = 4000     # the text it judges is cut after this
PICK_DESCRIPTION_CHARS = 200    # a tool's description in its list is cut after this
# how a detection decided (source): laya's questions, the llm's pick without laya, only the text scores (no laya and no
# llm pick), a short message (no questions asked). None: nothing decided
SOURCE_LAYA, SOURCE_LLM, SOURCE_TEXT, SOURCE_SHORT = "laya", "llm", "text", "short"


class ToolDetectionTask(Task):
    """detecting possible tools requests so we can offer the tools to the AI to use"""
    def __init__(self, prompt: str, tool_registry, infrastructure, excluded_tools: tuple = (), volume=None):
        """volume: the contact's files (SandboxVolume), the PROJECT_QUESTIONS are asked. None: they are not"""
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
        self._source: Optional[str] = None     # how it decided (SOURCE_*), None: nothing decided
        self._tool_scores: Dict[str, float] = {}    # tool -> its score: the best of its questions, the whole message's and its text_score

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

    def source(self) -> Optional[str]:
        """how the last detection decided: SOURCE_LAYA, SOURCE_LLM, SOURCE_TEXT or SOURCE_SHORT, None when nothing was decided
        (no laya, no llm pick and no text score: get_result's tool_names is None)"""
        return self._source

    def tool_scores(self) -> Dict[str, float]:
        """each tool's score of the last detection (laya_tune): the best of its questions, also on the whole message for a
        Tool.whole_message one, and its Tool.text_score"""
        return dict(self._tool_scores)

    def _candidates(self) -> Dict[str, Any]:
        """name -> class of the tools a detection picks from. the optional ones (PROMPT_TOOLS, companions like share_file)
        are offered without one, the excluded ones never"""
        return {name: cls for name, cls in self.tool_registry.tools.items()
                if not self.tool_registry.optional(name) and name not in self.excluded_tools}

    def _questions(self) -> dict:
        """one laya question per id "<tool>__<i>", a tool without questions gets one from its description, a Tool.text_only
        one none"""
        questions = {}
        for name, cls in self._candidates().items():
            if cls.text_only:
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
        """whether the contact's files hold a project (SandboxVolume.has_project), False when they can't be read"""
        try:
            self.project = self.volume.has_project()
        except Exception as e:
            logger.error(f"files of the contact not checked for a project {repr(e)}")
            self.project = False
        return self.project

    def _whole_ids(self, questions: dict) -> tuple:
        """the ids of the questions of the Tool.whole_message tools, judged on the whole message too"""
        whole = {name for name, cls in self._candidates().items() if cls.whole_message}
        return tuple(key for key in questions if key.rsplit("__", 1)[0] in whole)

    def _text_scores(self) -> Dict[str, float]:
        """the tools' scores from code (Tool.text_score), only the ones above 0"""
        scores = {name: cls.text_score(self.prompt) for name, cls in self._candidates().items()}
        for name, score in scores.items():
            if score > 0:
                self.scores[f"{name}{TEXT_SUFFIX}"] = (score, "text_score")
        return {name: score for name, score in scores.items() if score > 0}

    def _bands(self, probabilities: Dict[str, float]) -> Tuple[List[str], List[str]]:
        """(mandatory, recommended) of the tools by their scores and thresholds, ranked by the ToolRegistry"""
        self._tool_scores = dict(probabilities)
        mandatory = [name for name, p in probabilities.items() if p >= self.thresholds(name)[1]]
        recommended = [name for name, p in probabilities.items() if self.thresholds(name)[0] <= p < self.thresholds(name)[1]]
        return self.tool_registry.bands(mandatory, recommended)

    def _detect(self) -> Tuple[Optional[List[str]], List[str]]:
        text_scores = self._text_scores()

        if len(self.prompt.split()) < MIN_DETECTION_WORDS:
            logger.debug(f"tool detection skipped, fewer than {MIN_DETECTION_WORDS} words")
            self._source = SOURCE_SHORT
            return self._bands(text_scores)

        questions = self._questions()
        decided = self.infrastructure.decide_whole(self.prompt, questions, self._whole_ids(questions))
        if decided is None:
            return self._without_laya(text_scores)

        self._source = SOURCE_LAYA
        answers, whole_answers = decided
        probabilities = {}
        for suffix, scored in (("", answers), (WHOLE_SUFFIX, whole_answers)):
            for key, answer in scored.items():
                name = key.rsplit("__", 1)[0]
                probabilities[name] = max(probabilities.get(name, 0.0), answer.get("noul", 0.0))
                self.scores[f"{key}{suffix}"] = (answer.get("noul", 0.0), questions.get(key, {}).get("instructions", ""))

        # a fix or change of what was made earlier selects the PROJECT_TOOLS, only when there is a project to change
        project = probabilities.pop(PROJECT_KEY, 0.0)
        if project >= RECOMMENDED_THRESHOLD and self._has_project():
            for name in self.tool_registry.project_tools(self.excluded_tools):
                probabilities[name] = max(probabilities.get(name, 0.0), project)

        for name, score in text_scores.items():
            probabilities[name] = max(probabilities.get(name, 0.0), score)

        logger.debug("tool probabilities:\n" + Utils.pretty_scores({
            name: {"value": p, "recommended_threshold": self.thresholds(name)[0], "mandatory_threshold": self.thresholds(name)[1]}
            for name, p in probabilities.items()}, 20))
        return self._bands(probabilities)

    def _without_laya(self, text_scores: Dict[str, float]) -> Tuple[Optional[List[str]], List[str]]:
        """laya is down: the tools the llm picks (_pick) are recommended, never mandatory (the model decides), the text
        scores count as with laya. no llm pick: the text scores alone (a link: fetch_url), without any (None, [])"""
        picked = self._pick()
        if picked is None:
            self._source = SOURCE_TEXT if text_scores else None
            logger.info(f"tool detection without laya and llm pick: {'the text scores' if text_scores else 'nothing decided'}")
            return self._bands(text_scores) if text_scores else (None, [])
        self._source = SOURCE_LLM
        probabilities = {name: self.thresholds(name)[0] for name in picked}
        for name in picked:
            self.scores[f"{name}{LLM_SUFFIX}"] = (probabilities[name], "llm pick without laya")
        for name, score in text_scores.items():
            probabilities[name] = max(probabilities.get(name, 0.0), score)
        logger.info(f"tool detection without laya, the llm picked: {', '.join(picked) or 'nothing'}")
        return self._bands(probabilities)

    def _pick(self) -> Optional[List[str]]:
        """one llm call (TOOL_PICK_PROMPT, temperature 0, json) picks the candidates the text needs from their names and
        descriptions. the names it gives that are candidates, None without an llm or a usable json reply"""
        candidates = {name: cls for name, cls in self._candidates().items() if not cls.text_only}
        if self.infrastructure is None or not candidates:
            return None
        tools = "\n".join(f"- {name}: {' '.join(cls.get_description().split())[:PICK_DESCRIPTION_CHARS]}" for name, cls in candidates.items())
        text = self.prompt.strip()
        if len(text) > PICK_TEXT_CHARS:
            text = text[:PICK_TEXT_CHARS] + " ..."
        schema = {"type": "object", "properties": {"tools": {"type": "array", "items": {"type": "string", "enum": list(candidates)}}},
                  "required": ["tools"]}
        try:
            reply = self.infrastructure.chat(messages=[{"role": "user", "content": prompts.TOOL_PICK_PROMPT.format(tools=tools, text=text)}],
                                             temperature=0, seed=0, max_new_tokens=PICK_MAX_TOKENS, timeout=PICK_TIMEOUT, json_schema=schema)
        except Exception as e:     # the text scores still count (_without_laya)
            logger.error(f"tool detection without laya: the llm pick failed {repr(e)}")
            return None
        data = Utils.json_loads(reply) if reply else None
        picked = data.get("tools") if isinstance(data, dict) else data
        if not isinstance(picked, list):
            logger.warning(f"tool detection without laya: no usable llm pick: {str(reply)[:200]}")
            return None
        return [name for name in dict.fromkeys(str(name) for name in picked) if name in candidates]

    def trace(self, conversation_id: int, who: str) -> None:
        """the detection into the decision trace: the text it judged, each question's score and what it chose"""
        lines = [f"{score:.4f}  {key}  {question}" for key, (score, question) in sorted(self.scores.items(), key=lambda item: -item[1][0])]
        Trace.write(conversation_id, f"tool detection, {who}", f"TEXT:\n{self.prompt}\nSCORES (per question, best first):\n" + "\n".join(lines),
                    mandatory=self.tool_names, recommended=self.recommended, thresholds=[RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD],
                    excluded=list(self.excluded_tools), project_files=self.project, source=self._source)
