from .task_queue import Task
from . import prompts
from typing import List, Optional, Dict, Any, Tuple

from app.common import get_logger, Utils
from app.utils.trace import Trace
logger = get_logger()

MANDATORY_THRESHOLD = 0.7
RECOMMENDED_THRESHOLD = 0.5
PROJECT_KEY = "project"    # the ids of the ToolRegistry.PROJECT_QUESTIONS: "project__<i>"
WHOLE_SUFFIX = " (whole)"  # a question's score on the whole message in the trace, the plain id is its best part
TEXT_SUFFIX = "__text"     # a tool's Tool.text_score in the trace
LLM_SUFFIX = "__llm"       # a tool the llm picked without laya, or after a follow-up, in the trace (_pick)
PICK_MAX_TOKENS = 200      # the llm's pick without laya: {"tools": [...]} of a few names
PICK_TIMEOUT = 120         # seconds for that llm call
PICK_TEXT_CHARS = 4000     # the text it judges is cut after this
PICK_DESCRIPTION_CHARS = 200    # a tool's description in its list is cut after this
# how a detection decided (source): laya's questions, the llm's pick without laya, only the text scores (no laya and no
# llm pick), the chat/scene/work gate (per-tool questions skipped), a follow-up (the latest message refers back, the
# llm pick ran with the conversation history). None: nothing decided
SOURCE_LAYA, SOURCE_LLM, SOURCE_TEXT, SOURCE_GATE, SOURCE_FOLLOWUP = (
    "laya", "llm", "text", "gate", "followup")

GATE_KEY = "gate"           # ids gate__0, gate__1, ... one choice question per option_order rotation
GATE_THRESHOLD = 0.8        # skip the per-tool questions when P(chat)+P(scene) is at least this
GATE_INSTRUCTIONS = "What is the user's latest message mainly asking for?"
GATE_CRITERIA = {
    "chat": "casual conversation, small talk, or feelings, with no tool needed",
    "scene": "first-person acted or roleplay scene, even if it describes going somewhere or doing something, with no tool, lookup, or job requested",
    "work": "the user wants something done or looked up: a search, fact, link, file, code, map, image, audio, calculation, or a job to run",
}

FOLLOWUP_KEY = "followup"   # id followup__0, kept out of the tool probabilities like PROJECT_KEY
FOLLOWUP_RECOMMENDED_THRESHOLD = 0.4
FOLLOWUP_MANDATORY_THRESHOLD = 0.65
# examples in the question so laya can judge from the latest message alone; a self-contained new task
# (a project, an API, an app, a script) stays low, also when it ends with "tell me when the file is ready"
FOLLOWUP_QUESTION = (
    "Does the user's latest message only make sense as a follow-up to an earlier turn "
    "(for example 'that one', 'the file', 'it', 'the same', 'when it's ready', or 'yes, do that') "
    "and not as a complete request on its own? A self-contained task is not a follow-up, even a long one "
    "that starts a new project, API, app, or script."
)


class ToolDetectionTask(Task):
    """detecting possible tools requests so we can offer the tools to the AI to use"""
    def __init__(self, prompt: str, tool_registry, infrastructure, excluded_tools: tuple = (), volume=None,
                 db=None, conversation_id: Optional[int] = None):
        """volume: the contact's files (SandboxVolume), the PROJECT_QUESTIONS are asked. None: they are not.
        db and conversation_id: given, _pick sees the same conversation history a chat reply sees (ChatTask).
        None: only the text (find_tools)"""
        super().__init__()
        self.prompt = prompt
        self.excluded_tools = excluded_tools
        self.volume = volume
        self.project = None     # whether the files hold a project, None: not checked (no project question scored high enough)
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.db = db
        self.conversation_id = conversation_id
        self.tool_names = None
        self.recommended = []
        self.scores = {}    # question id -> (its score, the question), for the trace
        self._source: Optional[str] = None     # how it decided (SOURCE_*), None: nothing decided
        self._tool_scores: Dict[str, float] = {}    # tool -> its score: the best of its questions, the whole message's and its text_score
        self._followup: float = 0.0
        self._gate_probs: Dict[str, float] = {}    # P(chat), P(scene), P(work) of the last gate, {} when it was not used
        self._project_score: float = 0.0    # best project noul, 0 when the project questions were not asked
        self._laya_scores: Dict[str, float] = {}    # tool -> best laya noul, without pick floors or the project boost
        self._text: Dict[str, float] = {}    # Tool.text_score values above 0
        self._picked: Optional[List[str]] = None    # last _pick() names, None when it did not run

    def get_db(self):
        return self.db

    def get_conversation_id(self) -> Optional[int]:
        return self.conversation_id

    def followup_score(self) -> float:
        """the follow-up noul of the last detection, 0 when it was not asked"""
        return self._followup

    def gate_probabilities(self) -> Dict[str, float]:
        """P(chat), P(scene), P(work) of the last gate, {} when the gate was not used"""
        return dict(self._gate_probs)

    def project_score(self) -> float:
        """the best project question noul of the last detection, 0 when the project questions were not asked"""
        return self._project_score

    def laya_scores(self) -> Dict[str, float]:
        """each tool's best laya noul of the last detection, without the pick floors or the project boost,
        {} when the per-tool questions were not asked"""
        return dict(self._laya_scores)

    def text_score_values(self) -> Dict[str, float]:
        """the Tool.text_score values of the last detection, only the ones above 0"""
        return dict(self._text)

    def picked_tools(self) -> Optional[List[str]]:
        """the names the last _pick returned, None when it did not run"""
        return list(self._picked) if self._picked is not None else None

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
        """how the last detection decided: SOURCE_LAYA, SOURCE_LLM, SOURCE_TEXT, SOURCE_GATE or SOURCE_FOLLOWUP,
        None when nothing was decided (no laya, no llm pick and no text score: get_result's tool_names is None)"""
        return self._source

    def tool_scores(self) -> Dict[str, float]:
        """each tool's score of the last detection (laya_tune): the best of its questions, also on the whole message for a
        Tool.whole_message one, and its Tool.text_score"""
        return dict(self._tool_scores)

    def score_tool_questions(self) -> Dict[str, float]:
        """the tools' laya and text scores, always from the per-tool questions (laya_tune). the chat/scene/work gate and
        the follow-up path are not used, so a follow-up row is still scored per tool"""
        text_scores = self._text_scores()
        questions = self._questions()
        if self.infrastructure is None or not questions:
            self._tool_scores = dict(text_scores)
            return self.tool_scores()
        decided = self.infrastructure.decide_whole(self.prompt, questions, self._whole_ids(questions))
        if decided is None:
            self._tool_scores = dict(text_scores)
            return self.tool_scores()
        answers, whole_answers = decided
        self._source = SOURCE_LAYA
        self._tool_scores = self._laya_probabilities(questions, answers, whole_answers, text_scores)
        return self.tool_scores()

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

    def _followup_questions(self) -> dict:
        """the one follow-up noul, same wording in the gate batch and in the per-tool batch when the gate is not used"""
        return {f"{FOLLOWUP_KEY}__0": {"type": "noul", "instructions": FOLLOWUP_QUESTION}}

    def _followup_score(self, answers: dict) -> float:
        """the follow-up noul from a decide batch, 0 when the answer is missing or not a noul"""
        self._followup = float((answers.get(f"{FOLLOWUP_KEY}__0") or {}).get("noul", 0.0) or 0.0)
        self.scores[f"{FOLLOWUP_KEY}__0"] = (self._followup, FOLLOWUP_QUESTION)
        return self._followup

    def thresholds(self, name: str) -> Tuple[float, float]:
        """the (recommended, mandatory) thresholds of a tool: its own (Tool.thresholds) or the global ones"""
        cls = self.tool_registry.tools.get(name)
        return getattr(cls, "thresholds", None) or (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD)

    def _has_project(self) -> bool:
        """whether the contact's files hold a project (SandboxVolume.has_project). False when there is no volume,
        the files can't be read, or they hold none. self.project stays None when there was no volume to check"""
        if self.volume is None:
            return False
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
        self._text = {name: score for name, score in scores.items() if score > 0}
        return dict(self._text)

    def _bands(self, probabilities: Dict[str, float]) -> Tuple[List[str], List[str]]:
        """(mandatory, recommended) of the tools by their scores and thresholds, ranked by the ToolRegistry, without a
        priority tool that does not take over for this message (ToolRegistry.yielding)"""
        self._tool_scores = dict(probabilities)
        mandatory = [name for name, p in probabilities.items() if p >= self.thresholds(name)[1]]
        recommended = [name for name, p in probabilities.items() if self.thresholds(name)[0] <= p < self.thresholds(name)[1]]
        return self.tool_registry.bands(*self.tool_registry.yielding(mandatory, recommended, self.prompt))

    def _gate_questions(self) -> dict:
        """the chat/scene/work choice once per option_order rotation, and the follow-up noul, all in one decide call.
        every label sits in every slot equally often, so the position of a label does not decide the average"""
        labels = list(GATE_CRITERIA)
        k = len(labels)
        questions = {f"{GATE_KEY}__{r}": {
            "type": "choice",
            "instructions": GATE_INSTRUCTIONS,
            "criteria": GATE_CRITERIA,
            "option_order": [(i + r) % k for i in range(k)],
        } for r in range(k)}
        questions.update(self._followup_questions())
        return questions

    def _gate_probabilities(self, answers: dict) -> Dict[str, float]:
        """P(chat), P(scene), P(work) averaged over the rotations. missing labels count as 0"""
        totals = {label: 0.0 for label in GATE_CRITERIA}
        n = 0
        for key, answer in answers.items():
            if not str(key).startswith(f"{GATE_KEY}__"):
                continue
            probs = answer.get("probabilities") or {}
            for label in totals:
                totals[label] += float(probs.get(label, 0.0))
            n += 1
        if n:
            for label in totals:
                totals[label] /= n
        for label, p in totals.items():
            self.scores[f"{GATE_KEY}__{label}"] = (p, GATE_CRITERIA[label])
        self.scores[GATE_KEY] = (totals["chat"] + totals["scene"], GATE_INSTRUCTIONS)
        self._gate_probs = dict(totals)
        return totals

    def _text_blocks_gate(self, text_scores: Dict[str, float]) -> bool:
        """a text_score already at its recommended threshold (a link: fetch_url is mandatory): the gate must not skip"""
        return any(score >= self.thresholds(name)[0] for name, score in text_scores.items())

    def _gate(self) -> Tuple[Optional[dict], bool]:
        """(the decide answers, whether to skip the per-tool questions for chat or a scene). answers are None when
        Laya is down or the call is unusable; skip is then False, the message may be work"""
        if self.infrastructure is None:
            return None, False
        decided = self.infrastructure.decide(self.prompt, self._gate_questions())
        if not decided:
            return None, False
        probs = self._gate_probabilities(decided)
        skip = probs["chat"] + probs["scene"] >= GATE_THRESHOLD
        logger.debug(f"tool detection gate: chat={probs['chat']:.4f} scene={probs['scene']:.4f} work={probs['work']:.4f} "
                     f"threshold={GATE_THRESHOLD} skip={skip}")
        return decided, skip

    def _detect(self) -> Tuple[Optional[List[str]], List[str]]:
        text_scores = self._text_scores()

        followup = None     # None: the follow-up question has not been scored yet
        gate_skip = False
        if self._text_blocks_gate(text_scores):
            logger.debug("tool detection gate not used, a text_score already reaches recommended")
        else:
            decided, gate_skip = self._gate()
            if decided is not None:
                followup = self._followup_score(decided)

        if followup is not None and followup >= FOLLOWUP_MANDATORY_THRESHOLD:
            return self._from_followup(text_scores)

        if gate_skip and (followup is None or followup < FOLLOWUP_RECOMMENDED_THRESHOLD):
            self._source = SOURCE_GATE
            return self._bands(text_scores)

        questions = self._questions()
        if followup is None:
            questions.update(self._followup_questions())
        decided = self.infrastructure.decide_whole(self.prompt, questions, self._whole_ids(questions))
        if decided is None:
            return self._without_laya(text_scores)

        answers, whole_answers = decided
        if followup is None:
            followup = self._followup_score(answers)

        if followup >= FOLLOWUP_MANDATORY_THRESHOLD:
            self._record_laya(questions, answers, whole_answers)    # the per-tool scores stay in the trace only
            return self._from_followup(text_scores)

        self._source = SOURCE_LAYA
        mandatory, recommended = self._bands(self._laya_probabilities(questions, answers, whole_answers, text_scores))
        if followup >= FOLLOWUP_RECOMMENDED_THRESHOLD:
            return self._merge_followup_pick(text_scores, mandatory, recommended)
        return mandatory, recommended

    def _record_laya(self, questions: dict, answers: dict, whole_answers: dict) -> None:
        """the per-tool noul scores into the trace, including project, without changing the bands"""
        for suffix, scored in (("", answers), (WHOLE_SUFFIX, whole_answers)):
            for key, answer in scored.items():
                name = key.rsplit("__", 1)[0]
                noul = answer.get("noul", 0.0)
                if name == PROJECT_KEY:
                    self._project_score = max(self._project_score, noul)
                    if not suffix:
                        self.scores[key] = (noul, questions.get(key, {}).get("instructions", ""))
                    continue
                if name == FOLLOWUP_KEY:
                    if not suffix:
                        self.scores[key] = (noul, questions.get(key, {}).get("instructions", ""))
                    continue
                self._laya_scores[name] = max(self._laya_scores.get(name, 0.0), noul)
                self.scores[f"{key}{suffix}"] = (noul, questions.get(key, {}).get("instructions", ""))

    def _laya_probabilities(self, questions: dict, answers: dict, whole_answers: dict,
                            text_scores: Dict[str, float]) -> Dict[str, float]:
        """tool -> its best laya noul and text_score, project applied like a tool score when the files hold one.
        FOLLOWUP_KEY stays out of the result, the way PROJECT_KEY is popped"""
        probabilities = {}
        for suffix, scored in (("", answers), (WHOLE_SUFFIX, whole_answers)):
            for key, answer in scored.items():
                name = key.rsplit("__", 1)[0]
                probabilities[name] = max(probabilities.get(name, 0.0), answer.get("noul", 0.0))
                self.scores[f"{key}{suffix}"] = (answer.get("noul", 0.0), questions.get(key, {}).get("instructions", ""))

        self._project_score = probabilities.get(PROJECT_KEY, 0.0)
        self._laya_scores = {name: p for name, p in probabilities.items()
                             if name not in (PROJECT_KEY, FOLLOWUP_KEY)}
        project = probabilities.pop(PROJECT_KEY, 0.0)
        probabilities.pop(FOLLOWUP_KEY, None)
        if project >= RECOMMENDED_THRESHOLD and self._has_project():
            for name in self.tool_registry.project_tools(self.excluded_tools):
                probabilities[name] = max(probabilities.get(name, 0.0), project)

        for name, score in text_scores.items():
            probabilities[name] = max(probabilities.get(name, 0.0), score)

        logger.debug("tool probabilities:\n" + Utils.pretty_scores({
            name: {"value": p, "recommended_threshold": self.thresholds(name)[0], "mandatory_threshold": self.thresholds(name)[1]}
            for name, p in probabilities.items()}, 20))
        return probabilities

    def _pick_floors(self, picked: List[str]) -> Dict[str, float]:
        """a picked tool at its recommended threshold, a picked PRIORITY_TOOLS one at its mandatory threshold
        (the _without_laya rule)"""
        floors = {name: self.thresholds(name)[1 if name in self.tool_registry.PRIORITY_TOOLS else 0] for name in picked}
        for name in picked:
            self.scores[f"{name}{LLM_SUFFIX}"] = (floors[name], "llm pick")
        return floors

    def _from_followup(self, text_scores: Dict[str, float]) -> Tuple[Optional[List[str]], List[str]]:
        """the follow-up score is at least FOLLOWUP_MANDATORY_THRESHOLD: _pick decides, laya's per-tool scores stay in
        the trace only, the text scores merge as usual"""
        self._source = SOURCE_FOLLOWUP
        picked = self._pick()
        if not picked:
            logger.info(f"tool detection follow-up {self._followup:.4f}, no llm pick: "
                        f"{'the text scores' if text_scores else 'nothing decided'}")
            return self._bands(text_scores)
        probabilities = self._pick_floors(picked)
        for name, score in text_scores.items():
            probabilities[name] = max(probabilities.get(name, 0.0), score)
        logger.info(f"tool detection follow-up {self._followup:.4f}, the llm picked: {', '.join(picked)}")
        return self._bands(probabilities)

    def _merge_followup_pick(self, text_scores: Dict[str, float], mandatory: List[str], recommended: List[str]
                            ) -> Tuple[List[str], List[str]]:
        """the follow-up score is between the recommended and mandatory thresholds: keep laya's bands, add what _pick
        picks as recommended (priority tools follow the _without_laya rule)"""
        self._source = SOURCE_FOLLOWUP
        picked = self._pick()
        if not picked:
            logger.info(f"tool detection follow-up {self._followup:.4f} (mid), no llm pick, laya's bands kept")
            return mandatory, recommended
        probabilities = dict(self._tool_scores)
        for name, floor in self._pick_floors(picked).items():
            probabilities[name] = max(probabilities.get(name, 0.0), floor)
        for name, score in text_scores.items():
            probabilities[name] = max(probabilities.get(name, 0.0), score)
        logger.info(f"tool detection follow-up {self._followup:.4f} (mid), the llm picked: {', '.join(picked)}")
        return self._bands(probabilities)

    def _without_laya(self, text_scores: Dict[str, float]) -> Tuple[Optional[List[str]], List[str]]:
        """laya is down: the tools the llm picks (_pick) are recommended (the model decides), a PRIORITY_TOOLS one mandatory
        as when laya is sure of it (ToolRegistry.bands: it runs alone), the text scores count as with laya. no llm pick:
        the text scores alone (a link: fetch_url), without any (None, [])"""
        picked = self._pick()
        if picked is None:
            self._source = SOURCE_TEXT if text_scores else None
            logger.info(f"tool detection without laya and llm pick: {'the text scores' if text_scores else 'nothing decided'}")
            return self._bands(text_scores) if text_scores else (None, [])
        self._source = SOURCE_LLM
        probabilities = self._pick_floors(picked)
        for name, score in text_scores.items():
            probabilities[name] = max(probabilities.get(name, 0.0), score)
        logger.info(f"tool detection without laya, the llm picked: {', '.join(picked) or 'nothing'}")
        return self._bands(probabilities)

    def _pick_project_hint(self) -> str:
        """a line about whether the contact's files already hold a project, only on the follow-up pick.
        empty when this is not a follow-up pick or the files were not checked (no volume)"""
        if self._source != SOURCE_FOLLOWUP or self.volume is None:
            return ""
        if self._has_project():
            return prompts.TOOL_PICK_PROJECT_HINT
        return prompts.TOOL_PICK_NO_PROJECT_HINT

    def _pick_messages(self, tools: str, text: str) -> list:
        """the messages _pick sends: the same conversation history a chat reply sees (ChatTask.conversation_messages),
        then the pick prompt. without a db or conversation, only the pick prompt (find_tools).
        on the follow-up route the prompt also gets a line about whether the files already hold a project"""
        db, conversation_id = self.get_db(), self.get_conversation_id()
        history, note = [], ""
        hint = ""
        if db is not None and conversation_id is not None:
            from .chat_task import ChatTask     # chat_task imports the execution task, which imports this
            history, note = ChatTask.conversation_messages(db, conversation_id)
            hint = prompts.TOOL_PICK_HISTORY_HINT
        prompt = prompts.TOOL_PICK_PROMPT.format(history=hint, project=self._pick_project_hint(),
                                                 tools=tools, text=text)
        if note:
            prompt = f"{note}\n\n{prompt}"
        return list(history) + [{"role": "user", "content": prompt}]

    def _pick(self) -> Optional[List[str]]:
        """one llm call (TOOL_PICK_PROMPT, temperature 0, json) picks the candidates the text needs from their names and
        descriptions, with the same conversation history a chat reply sees when db and conversation_id were given.
        the names it gives that are candidates, None without an llm or a usable json reply"""
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
            reply = self.infrastructure.chat(messages=self._pick_messages(tools, text),
                                             temperature=0, seed=0, max_new_tokens=PICK_MAX_TOKENS, timeout=PICK_TIMEOUT, json_schema=schema)
        except Exception as e:     # the text scores still count (_without_laya, _from_followup)
            logger.error(f"tool detection llm pick failed {repr(e)}")
            return None
        data = Utils.json_loads(reply) if reply else None
        picked = data.get("tools") if isinstance(data, dict) else data
        if not isinstance(picked, list):
            logger.warning(f"tool detection llm pick: no usable json reply: {str(reply)[:200]}")
            return None
        names = [name for name in dict.fromkeys(str(name) for name in picked) if name in candidates]
        self._picked = names
        return names

    def trace(self, conversation_id: int, who: str) -> None:
        """the detection into the decision trace: the text it judged, each question's score and what it chose"""
        lines = [f"{score:.4f}  {key}  {question}" for key, (score, question) in sorted(self.scores.items(), key=lambda item: -item[1][0])]
        Trace.write(conversation_id, f"tool detection, {who}", f"TEXT:\n{self.prompt}\nSCORES (per question, best first):\n" + "\n".join(lines),
                    mandatory=self.tool_names, recommended=self.recommended, thresholds=[RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD],
                    excluded=list(self.excluded_tools), project_files=self.project, source=self._source)
