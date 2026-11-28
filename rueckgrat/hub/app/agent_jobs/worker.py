"""
#230 the agents' one way to use tools: a loop of tool calls. each turn the model sees its goal, its tools and what it did
so far, writes one to CALLS_PER_TURN calls, sees their results and decides the next turn, until it calls finish or its
budget (MAX_CALLS calls, TIME_LIMIT seconds) is used up: all three end it the same way, nothing it claims is checked here.
a job's Controller spawns workers for its plan and runs each step's check after it (Check); a task or companion pass runs
one for its lookup (lookup).

the replies: with JSON_REPLIES the node holds them to turn_schema (a grammar). its "note" comes first, so a model writes
its reasoning there before the calls. the node turns qwen's thinking off and keeps reasoning_content and <think> out of
the content, so thinking never meets the grammar; a model that thinks inside the grammar can only think in the note. an
empty reply from a node that answered is asked again once without the grammar (_ask), one from a node that did not answer is
not (nothing helps): step waits and counts the failed turn. a turn without a call costs one of the worker's calls, and
MAX_FAILED_TURNS of them in a row end it with an error: a down llm does not loop until the time limit. without JSON_REPLIES the model thinks freely and
parse_turn reads json, fences and <tool_call> xml, at the risk of replies it can't read (the model sees that as an error).
"""
import itertools
import json
import os
import re
import shlex
import time
from typing import Optional, Dict, Any, List, Tuple

from . import prompts
from .agent_job import AgentJob, JOB_LLM_TIMEOUT
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH

from app.common import get_logger
logger = get_logger()

MAX_CALLS = int(os.environ.get("HUB_JOB_WORKER_CALLS") or 100)                 # tool calls of one worker
TIME_LIMIT = 60 * float(os.environ.get("HUB_JOB_WORKER_MINUTES") or 30)       # seconds of one worker, a slow model needs them
# its replies are json of TURN_SCHEMA (the node's grammar), else free text: the parser takes json, fences and <tool_call> xml
JSON_REPLIES = (os.environ.get("HUB_JOB_WORKER_JSON") or "true").lower() in ("1", "true", "yes")
CALLS_PER_TURN = 3
KEEP_TURNS = 4              # the last turns the model sees whole, the ones before as one line per call (_history)
EARLIER_SHARE = 0.1         # of a llama slot's context for those lines, the oldest turns that do not fit are left out (_earlier_chars)
DEFAULT_SLOT_TOKENS = 8192  # the context without a known slot (Infrastructure.chat's context_size)
MAX_FAILED_TURNS = 3        # turns in a row without a call that end a worker with an error (step)
FAILED_CHAT_WAIT = 2.0      # seconds before the next turn after a chat the node did not answer (step)
UNREADABLE_CHARS = 120      # of a call that could not be read, in its error
RESULT_CHARS = 4000         # of one call's result in a turn, its start and its end
ARGUMENT_CHARS = 1500       # of one argument of a call in the turns the model sees again (an edit's whole file)
LINE_CHARS = 160            # of one call in the short lines of the older turns
MIN_LLM_SECONDS = 60        # an llm call gets at least this, even when the time limit is nearly up
CHARS_PER_TOKEN = 3         # of code and json, for the reply size the prompt names (_reply_chars)
MIN_REPLY_TOKENS = 4096     # without an llm (Infrastructure.MIN_LONG_REPLY_TOKENS)
FINISH = "finish"
PASS_CALLS = 8              # tool calls of a task's or companion pass's lookup (lookup)
# a job's worker has these (Worker.always): what it may need for a step, not photos, share_file (the job delivers the
# files itself, Controller) or the chat's tools (spawn_job, remember, poll, show_map, task, find_tools)
JOB_TOOLS = ("bash", "read_file", "edit_file", "write_file", "reset_sandbox", "websearch", "fetch_url",
             "calculate", "convert", "current_time", "date_calc", "weather", "price_finder", "generate_image",
             "join_files", "text_to_speech", "search_memory")
CHANGING_TOOLS = {"bash", "edit_file"}  # a worker with one of them backs the files up before it starts (_back_up)
EXIT_CODE = re.compile(r"^exit code (-?\d+)( \(stopped)?", re.MULTILINE)     # a bash result (BashTool._run)
THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)
FUNCTION = re.compile(r"<function=([\w.-]+)>(.*?)(?:</function>|(?=<function=)|$)", re.DOTALL)
PARAMETER = re.compile(r"<parameter=([\w.-]+)>\n?(.*?)\n?(?:</parameter>|(?=<parameter=)|$)", re.DOTALL)


def turn_schema(names: List[str]) -> dict:
    """the json a worker's turn is: a note and 1 to CALLS_PER_TURN calls of the names. a call's other keys are free
    (llama.cpp's grammar allows them with additionalProperties), the tools check their own parameters"""
    return {"type": "object", "properties": {
        "note": {"type": "string"},
        "calls": {"type": "array", "minItems": 1, "maxItems": CALLS_PER_TURN, "items": {
            "type": "object", "properties": {"tool": {"type": "string", "enum": list(names)}},
            "required": ["tool"], "additionalProperties": True}}},
        "required": ["note", "calls"]}


def _value(text: str):
    """a <parameter> value: json when it is a list, an object or a number (files, start), else the text"""
    stripped = text.strip()
    if stripped[:1] in ("[", "{") or re.fullmatch(r"-?\d+", stripped):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    return text


def _call(data) -> Optional[Dict[str, Any]]:
    """a call in one of the forms models write: {"tool", ...} or {"name", "arguments"} (native tool calls), None else"""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("tool"), str):
        return data
    if isinstance(data.get("name"), str) and isinstance(data.get("arguments", {}), (dict, str)):
        arguments = data.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                return None
        return {"tool": data["name"], **arguments} if isinstance(arguments, dict) else None
    return None


def parse_turn(text: str, names: List[str]) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """(note, calls, errors) of a worker's reply: TURN_SCHEMA json, single calls as json (also in fences, or as
    {"name", "arguments"}) or <tool_call><function=NAME><parameter=KEY>VALUE xml. nothing is dropped silently: what
    can't be read, a call of a tool that is not one of names and a reply without any call each give an error the model
    sees in its next turn"""
    from app.tools.tool_registry import ToolRegistry     # the registry's tools import the agent jobs
    text = THINK.sub("", text or "").strip()
    note, calls, errors = "", [], []
    blocks = TOOL_CALL.findall(text)
    if blocks or "<function=" in text:
        note = text[:text.find("<tool_call>") if blocks else text.find("<function=")].strip()
        for block in blocks or [text]:
            functions = FUNCTION.findall(block)
            if functions:
                calls += [{"tool": name, **{key: _value(value) for key, value in PARAMETER.findall(body)}} for name, body in functions]
                continue
            try:
                call = _call(json.loads(block))
            except ValueError:
                call = None
            if call is None:
                errors.append(prompts.WORKER_UNREADABLE_PART.format(text=block[:UNREADABLE_CHARS]))
            else:
                calls.append(call)
    else:
        found = list(ToolRegistry._json_objects(text))
        for item in found:
            try:
                data = json.loads(item)
            except ValueError as e:
                errors.append(prompts.WORKER_UNREADABLE_PART.format(text=f"{item[:UNREADABLE_CHARS]} ({e})"))
                continue
            if isinstance(data, dict) and isinstance(data.get("calls"), list):
                note = note or str(data.get("note") or "")
                items = data["calls"]
            else:
                items = [data]
            for entry in items:
                call = _call(entry)
                if call is None:
                    errors.append(prompts.WORKER_UNREADABLE_PART.format(text=json.dumps(entry, ensure_ascii=False)[:UNREADABLE_CHARS]))
                else:
                    calls.append(call)
        end = 0
        for item in found:
            end = text.index(item, end) + len(item)
        if "{" in text[end:]:     # an object that was not closed: the reply was cut off (its token limit)
            errors.append(prompts.WORKER_CUT_OFF_PART)
        if not found:
            note = text[:300]
    known = [call for call in calls if call["tool"] in names]
    errors += [prompts.WORKER_UNKNOWN_TOOL_PART.format(tool=call["tool"], tools=", ".join(names)) for call in calls if call["tool"] not in names]
    if not known and not errors:
        errors.append(prompts.WORKER_NO_CALL_PART)
    return note.strip(), known, errors


def clip(text: str, limit: int = RESULT_CHARS) -> str:
    """text up to limit characters: its start and its end (the errors are there), the cut said"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = limit * 3 // 4
    return f"{text[:head]}\n[... {len(text) - limit} characters cut]\n{text[-(limit - head):]}"


def lookup(agent: AgentJob, goal: str, always=(), excluded=(), failed: bool = True) -> Tuple[str, "Worker"]:
    """#230 a task's or companion pass's tools: a Worker on the agent's conversation reaches goal (PASS_GOAL_PART) in the
    agent's thread, with PASS_CALLS calls and what is left of the agent's time. its tools: always, never excluded (a
    companion: the user's settings). the files and data it holds go to the agent's message (attachments, held_data).
    returns (what it found for the agent's prompt: its result_text, a failed one's reason, "" for that when not failed,
    the worker)"""
    left = agent.deadline - time.monotonic() if agent.deadline else TIME_LIMIT
    worker = Worker(f"{agent.role} lookup", prompts.PASS_GOAL_PART.format(goal=goal), time_limit=max(MIN_LLM_SECONDS, min(TIME_LIMIT, left)),
                    infrastructure=agent.infrastructure, tool_context=agent.tool_context)
    worker.always = tuple(name for name in always if name not in excluded)
    worker.max_calls = PASS_CALLS
    result = worker.run() or {"error": "no result"}
    agent.attachments += worker.attachments
    agent.held_data.update(worker.held_data)
    if "error" in result:
        return (prompts.PASS_FAILED_PART.format(reason=result["error"]) if failed else ""), worker
    return Worker.result_text(result), worker


class Worker(AgentJob):
    """#230 an agent that uses tools: a worker of an agent job (Controller.spawn) or a pass's lookup (lookup). one turn
    per step() (AgentJob.run: its time limit), see the module. its result {summary, details, tools, saved, changed,
    attachments}, {error} only when it crashed (AgentJob._run_safe)"""

    def __init__(self, role: str, prompt: str, job_id: Optional[str] = None, time_limit: float = TIME_LIMIT, infrastructure=None,
                 tool_context: Optional[Dict[str, Any]] = None):
        super().__init__(role, prompt, job_id, time_limit, infrastructure, tool_context)
        self.check = ""             # its step's check command, shown in its prompt (Controller.spawn)
        self._folder = ""           # the job's folder below MOUNT_PATH, "" for a pass's lookup (set_folder)
        self.max_calls = MAX_CALLS
        self.always = JOB_TOOLS     # its tools (a pass's lookup: its own)
        self.calls = 0              # the tool calls so far, a turn without a call counts as one
        self.failed_turns = 0       # the turns in a row without a call (step)
        self.tools: Optional[List[str]] = None      # its tools (_setup), finish besides
        self.turns: List[Dict[str, Any]] = []       # {"note", "calls": [{"call", "text", "ok"}]} in order
        self.commands: List[Tuple[str, int]] = []   # (command, exit code) of its bash calls
        self.saved: List[str] = []                  # full paths its tools wrote (edit_file, write_file, text_to_speech)
        self._before: Optional[Dict[str, tuple]] = None     # the project folder's files when it started (SandboxVolume.stats)
        self._first = ""            # its first message without the earlier turns (_prompt, made once)

    def set_folder(self, folder: str) -> None:
        """the job's folder below MOUNT_PATH (Controller._choose_folder), "" without one"""
        self._folder = folder

    # ------------------------------------------------------------ the loop

    def step(self) -> bool:
        """one turn: ask, run its calls. True when it called finish (the calls before it ran, the ones after it do not)
        or its calls are used up: both end it as done. a turn without a call counts one call and, MAX_FAILED_TURNS in a
        row, ends it with an error (the llm's, when the node did not answer); after a chat the node did not answer it
        waits FAILED_CHAT_WAIT seconds"""
        if self.tools is None:
            self._setup()
        if self.calls >= self.max_calls:
            self._done(self._last_note())
            return True
        note, calls, errors = parse_turn(self._ask(), self.tools + [FINISH])
        turn = {"note": note, "calls": [{"call": None, "text": error, "ok": False} for error in errors]}
        self.turns.append(turn)
        self.failed_turns = 0 if calls else self.failed_turns + 1
        if not calls:
            self.calls += 1
            if self.failed_turns >= MAX_FAILED_TURNS:
                self._fail()
                return True
            if self.llm_error:
                self._stop.wait(FAILED_CHAT_WAIT)
        for index, call in enumerate(calls):
            if self._stop.is_set():
                return True
            if call["tool"] == FINISH:
                self._done(str(call.get("summary") or "").strip() or note)
                return True
            if index >= CALLS_PER_TURN or self.calls >= self.max_calls:
                turn["calls"].append({"call": call, "text": prompts.WORKER_NOT_RUN_PART.format(count=CALLS_PER_TURN), "ok": False})
                continue
            self.calls += 1
            text, ok = self._run(call)
            turn["calls"].append({"call": call, "text": text, "ok": ok})
        return False

    def _fail(self) -> None:
        """its result {error}: MAX_FAILED_TURNS turns in a row without a call, why the llm did not answer if it did not"""
        reason = (prompts.WORKER_NO_ANSWER_PART.format(turns=self.failed_turns, reason=self.llm_error[:LINE_CHARS]) if self.llm_error
                  else prompts.WORKER_NO_CALLS_PART.format(turns=self.failed_turns))
        self.result = {"error": reason}
        logger.warning(f"worker {self.role} {self.job_id}: {reason}")
        self.trace("failed", ok=False, error=reason, calls=self.calls)

    def run(self) -> Optional[Dict[str, Any]]:
        """AgentJob.run, its time limit ends it as done too"""
        super().run()
        if self.timed_out:
            self._done(self._last_note())
        return self.result

    def _last_note(self) -> str:
        """its last note, "" without one: the summary of a worker that did not call finish"""
        return next((turn["note"] for turn in reversed(self.turns) if turn.get("note")), "")

    def _setup(self) -> None:
        """its tools and its folder's files before it starts: always, of the ones that can be used now (once, not per
        turn). one with tools that change files backs them up first (_back_up), one with a folder and the shell starts
        in it (_enter)"""
        registry = self.tool_context["tool_registry"] if self.tool_context else None
        if registry is None:
            self.tools, self._first = [], self._prompt()
            return
        self.tools = registry.ordered_names(registry.available(list(self.always)))
        self.trace("tools", tools=self.tools)
        if CHANGING_TOOLS & set(self.tools):
            self._back_up()
        if self._folder and "bash" in self.tools:
            self._enter()
        self._before = self._snapshot()
        self._first = self._prompt()
        logger.info(f"worker {self.role} {self.job_id}: tools {self.tools}, folder {self._folder or 'none'}")

    def _enter(self) -> None:
        """makes its folder (a new project's on a contact without files yet) and moves the conversation's shell there,
        so its commands start in it. not one of its calls, a failure does not stop it"""
        folder = shlex.quote(self.folder())
        context = self.tool_context
        try:
            context["tool_registry"].execute(context["user_id"], context["contact_id"], context["conversation_id"],
                                             {"tool": "bash", "command": f"mkdir -p {folder} && cd {folder}",
                                              "llm_timeout": JOB_LLM_TIMEOUT, "background": True})
        except Exception as e:
            logger.warning(f"worker {self.role} {self.job_id}: folder not entered {repr(e)}")

    # ------------------------------------------------------------ the model's turn

    def _ask(self) -> str:
        """the model's next turn: the prompt with its goal and tools, the turns so far (_history), the budget left.
        its time: what is left of the limit, at least MIN_LLM_SECONDS"""
        left = max(0.0, self.deadline - time.monotonic()) if self.deadline else float(self.time_limit)
        earlier, turns = self._history()
        messages = [{"role": "user", "content": self._first + earlier}] + turns
        status = prompts.WORKER_BUDGET_LEFT_PART.format(calls=self.max_calls - self.calls, total=self.max_calls, minutes=int(left // 60))
        if messages[-1]["role"] == "user":
            messages[-1] = {"role": "user", "content": f"{messages[-1]['content']}\n\n{status}"}
        timeout = max(MIN_LLM_SECONDS, min(JOB_LLM_TIMEOUT, left))
        if not JSON_REPLIES:
            return self.chat(messages, 0.3, timeout=timeout)
        reply = self.chat(messages, 0.3, json_schema=turn_schema(self.tools + [FINISH]), timeout=timeout)
        if reply.strip() or self.llm_error:     # a node that did not answer is no use to ask again
            return reply
        # an empty reply with the grammar (a node or model that can't hold it, e.g. thinking inside it): once more without
        logger.warning(f"worker {self.role} {self.job_id}: no reply with the json grammar, asked again without it")
        self.trace("no_json_reply", ok=False)
        left = max(0.0, self.deadline - time.monotonic()) if self.deadline else float(self.time_limit)
        return self.chat(messages, 0.3, timeout=max(MIN_LLM_SECONDS, min(JOB_LLM_TIMEOUT, left)))

    def _prompt(self) -> str:
        """the first message: role, goal with the project line and the earlier results, the check, the tools (with
        the contact's projects as they were when it started)"""
        task, marker, earlier = self.prompt.partition(prompts.RESULTS_MARKER_PART)
        scope = None
        if self.tool_context:
            scope = {key: self.tool_context[key] for key in ("user_id", "contact_id", "conversation_id")}
            scope["loop"] = True
        registry = self.tool_context["tool_registry"] if self.tool_context else None
        tools = ""
        if registry and self.tools:     # the notes of its own tools only
            tools = registry.get_tools_prompt(self.tools, scope) + \
                registry.notes(self.tools, tuple(name for name in registry.tools if name not in self.tools))
        folder = prompts.FOLDER_PART.format(path=self.folder()) if self._folder else ""
        return prompts.WORKER_PROMPT.format(
            role=self.role, task=f"{task}{folder}{marker}{earlier}",
            check=prompts.WORKER_CHECK_PART.format(check=self.check, folder=self.folder()) if self.check else "",
            tools=tools + prompts.WORKER_FINISH_TOOL_PART, per_turn=CALLS_PER_TURN, reply_chars=self._reply_chars())

    def folder(self) -> str:
        """the folder it works in, absolute: the job's folder, else its conversation's workdir (where bash starts),
        MOUNT_PATH without a conversation"""
        if self._folder:
            return f"{MOUNT_PATH}/{self._folder}"
        if self.tool_context and self.tool_context.get("conversation_id") is not None:
            return SandboxVolume.workdir(self.tool_context["conversation_id"])
        return MOUNT_PATH

    def _reply_chars(self) -> int:
        """about how many characters one reply can hold: the llm's reply tokens (Infrastructure.long_reply_tokens, a share of
        its context) in characters of code"""
        tokens = self.infrastructure.long_reply_tokens() if self.infrastructure is not None else 0
        return (tokens or MIN_REPLY_TOKENS) * CHARS_PER_TOKEN

    def _history(self) -> Tuple[str, List[Dict[str, str]]]:
        """the turns so far: the older ones as short lines (_earlier) for the end of the first message, "" for none,
        and the last KEEP_TURNS whole as assistant (its calls) and user (their results) messages"""
        older, recent = self.turns[:-KEEP_TURNS], self.turns[-KEEP_TURNS:]
        messages = []
        for turn in recent:
            calls = [self._shown(entry["call"]) for entry in turn["calls"] if entry["call"] is not None]
            messages.append({"role": "assistant", "content": json.dumps({"note": turn["note"], "calls": calls}, ensure_ascii=False, separators=(",", ":"))})
            results = "\n\n".join(f"[{number}] {entry['call']['tool'] if entry['call'] else 'error'}: {entry['text']}"
                                  for number, entry in enumerate(turn["calls"], 1))
            messages.append({"role": "user", "content": prompts.WORKER_RESULTS_PART.format(results=results)})
        return self._earlier(older), messages

    def _earlier(self, older: List[Dict[str, Any]]) -> str:
        """the older turns for the end of the first message, "" for none: one short line per call under a line for the
        turn (its number and note), the same turn in a row once ("5-40 (the same 36 times):"). the newest turns that fit
        _earlier_chars, the ones before are left out (WORKER_LEFT_OUT_PART)"""
        turns = [(turn["note"][:LINE_CHARS], tuple(self._short(entry) for entry in turn["calls"])) for turn in older]
        blocks, number = [], 1
        for (note, lines), same in itertools.groupby(turns):
            count = len(list(same))
            head = f"{number}." if count == 1 else f"{number}-{number + count - 1} (the same {count} times):"
            blocks.append((count, "\n".join([f"{head} {note}".rstrip(), *(f"- {line}" for line in lines)])))
            number += count
        room, kept = self._earlier_chars(), []
        for _, text in reversed(blocks):
            room -= len(text) + 1
            if room < 0:
                break
            kept.append(text)
        left_out = sum(count for count, _ in blocks[:len(blocks) - len(kept)])
        lines = ([prompts.WORKER_LEFT_OUT_PART.format(count=left_out)] if left_out else []) + kept[::-1]
        return prompts.WORKER_EARLIER_PART.format(lines="\n".join(lines)) if lines else ""

    def _earlier_chars(self) -> int:
        """how many characters the lines of the older turns may have: EARLIER_SHARE of the llm's slot context in
        characters (Infrastructure.slot_context, DEFAULT_SLOT_TOKENS when unknown), so the first message stays a small
        part of the prompt while a long job keeps as much of its history as fits"""
        tokens = (self.infrastructure.slot_context() if self.infrastructure is not None else None) or DEFAULT_SLOT_TOKENS
        return int(tokens * CHARS_PER_TOKEN * EARLIER_SHARE)

    @staticmethod
    def _shown(call: Dict[str, Any]) -> Dict[str, Any]:
        """a call as the model sees it again, long arguments cut (an edit's whole file)"""
        return {key: clip(value, ARGUMENT_CHARS) if isinstance(value, str) else value for key, value in call.items()}

    @staticmethod
    def _short(entry: Dict[str, Any]) -> str:
        """one call of an older turn in a line: the tool, its arguments' start, how it went"""
        call = entry["call"]
        if call is None:
            return f"error: {' '.join(entry['text'].split())[:LINE_CHARS]}"
        arguments = " ".join(json.dumps({k: v for k, v in call.items() if k != "tool"}, ensure_ascii=False, separators=(",", ":")).split())
        code = EXIT_CODE.search(entry["text"] or "")
        outcome = f"exit code {code.group(1)}" if code else ("ok" if entry["ok"] else f"failed: {' '.join(entry['text'].split())[:80]}")
        return f"{call['tool']} {arguments[:LINE_CHARS]} -> {outcome}"

    # ------------------------------------------------------------ the calls

    def _run(self, call: Dict[str, Any]) -> Tuple[str, bool]:
        """runs one call (ToolRegistry.execute) in the background with an agent's llm timeout: (its result text clipped,
        whether it worked: no error, a bash command's exit code 0, or 124 when its own timeout stopped a program that was
        still running). keeps what it wrote and holds"""
        registry, context = self.tool_context["tool_registry"], self.tool_context
        started = time.monotonic()
        try:
            results = registry.execute(context["user_id"], context["contact_id"], context["conversation_id"],
                                       {**call, "llm_timeout": JOB_LLM_TIMEOUT, "background": True}) or {}
            result = results.get(call["tool"])
        except Exception as e:
            logger.error(f"worker {self.role} {self.job_id}: {call['tool']} failed {repr(e)}")
            result = {"error": repr(e)}
        ms = int((time.monotonic() - started) * 1000)
        if not isinstance(result, dict):
            text, ok = (prompts.WORKER_NO_RESULT_PART if result is None else str(result)), result is not None
        else:
            text = str(result.get("error") or result.get("text") or "") or \
                json.dumps({k: v for k, v in result.items() if k not in ("tool", "attachments")}, ensure_ascii=False, default=str)
            ok = "error" not in result
            self.attachments += result.get("attachments") or []
            self.held_data.update(registry.held_data({call["tool"]: result}))     # a poll, a map, a price ranking
            self.saved = list(dict.fromkeys(self.saved + list(result.get("saved") or [])))
        if call["tool"] == "bash":
            ok = self._exit(str(call.get("command") or ""), text) and ok
        self.trace_call(call, None if ok else " ".join(text.split())[:300], ms)
        return clip(text), ok

    def _exit(self, command: str, text: str) -> bool:
        """keeps a bash command with its exit code (commands), whether it worked (0, or 124 of its own timeout)"""
        match = EXIT_CODE.search(text)
        if not match:
            return False
        code = int(match.group(1))
        if match.group(2):      # the sandbox stopped it (COMMAND_TIMEOUT), not the command's own timeout
            code = -1
        self.commands.append((command, code))
        return code in (0, 124)

    # ------------------------------------------------------------ its files and its result

    def _back_up(self) -> None:
        """the contact's files into the hub's backup (SandboxVolume.snapshot), what a files reset brings back. a failed
        backup does not stop the worker"""
        try:
            SandboxVolume(self.tool_context["user_id"], self.tool_context["contact_id"]).snapshot()
            self.trace("backup", ok=True)
        except Exception as e:
            logger.warning(f"worker {self.role} {self.job_id}: files not backed up {repr(e)}")
            self.trace("backup", ok=False, error=str(e)[:300])

    def _snapshot(self) -> Optional[Dict[str, tuple]]:
        """its folder's files {path: (size, mtime)}, None without a folder or when they can't be read"""
        if not self._folder or not self.tool_context:
            return None
        try:
            return SandboxVolume(self.tool_context["user_id"], self.tool_context["contact_id"]).stats(self._folder)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.warning(f"worker {self.role} {self.job_id}: project files not read {repr(e)}")
            return None

    def _changed(self) -> List[str]:
        """the full paths of the project files it made, changed or deleted, [] when unknown"""
        after = self._snapshot()
        if after is None or self._before is None:
            return []
        paths = [path for path, stat in after.items() if self._before.get(path) != stat] + [path for path in self._before if path not in after]
        return [f"{MOUNT_PATH}/{path}" for path in sorted(paths)]

    def _done(self, summary: str) -> None:
        """its result: its summary, what the job saw of its work (_progress), the files it changed and its tools wrote"""
        changed = self._changed()
        saved = list(dict.fromkeys(self.saved + changed))
        self.result = {"summary": summary, "details": self._progress(changed), "tools": self.called(), "changed": changed,
                       **({"attachments": self.attachments} if self.attachments else {}),
                       **({"saved": saved} if saved else {})}
        self.trace("done", ok=True, summary=summary, calls=self.calls, changed=len(changed))

    def called(self) -> List[str]:
        """the tools it called, in order"""
        return list(dict.fromkeys(entry["call"]["tool"] for turn in self.turns for entry in turn["calls"] if entry["call"] is not None))

    def _progress(self, changed: List[str]) -> str:
        """what the job saw of its work: the files it changed, its last commands with their exit codes"""
        lines = []
        if changed:
            lines.append(prompts.WORKER_CHANGED_PART.format(files=", ".join(changed[:30]) + (" ..." if len(changed) > 30 else "")))
        if self.commands:
            lines.append(prompts.WORKER_COMMANDS_PART.format(commands="; ".join(
                f"`{' '.join(command.split())[:120]}` exit {code}" for command, code in self.commands[-8:])))
        return "\n".join(lines)

    @staticmethod
    def result_text(result: Dict[str, Any]) -> str:
        """a worker's result as text for the steps after it and the merge: its summary, details, the tools
        it called, the files its tools wrote with their full paths (so a later worker uses them instead of making them
        again) and the files it holds for the user"""
        saved = prompts.SAVED_FILES_PART.format(paths=", ".join(result["saved"])) if result.get("saved") else ""
        names = [str(held.get("name")) for held in result.get("attachments") or [] if held.get("name")]
        held = prompts.ATTACHED_FILES_PART.format(names=", ".join(names)) if names else ""
        used = prompts.TOOLS_USED_PART.format(tools=", ".join(result["tools"]) or "none") if "tools" in result else ""
        return "\n".join(part for part in (result.get("summary") or "", result.get("details") or "", used, saved, held) if part).strip()
