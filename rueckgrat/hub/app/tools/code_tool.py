import base64
import json
import random
import re
from typing import Dict, Any, List, Tuple
from .tool import Tool
from . import prompts
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, PROJECTS

from app.common import get_logger, MessageQueue
logger = get_logger()

LANGUAGES = ("python", "javascript", "cpp", "java", "go")
ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript", "nodejs": "javascript",
           "c++": "cpp", "golang": "go"}
RUN_TIMEOUT = 60            # seconds for the program
INSTALL_TIMEOUT = 180       # seconds for installing the libraries and the program
MAX_OUTPUT = 4000           # characters of stdout and of stderr for the model
MAX_LIBRARIES = 10
CONTEXT_MESSAGES = 6        # the latest conversation messages the code writer sees
MAX_MESSAGE_CHARS = 6000
# every run: limits, no new privileges. network only when libraries must be installed (pip, npm, apt, go get)
RUNTIME_CONFIGS = {"mem_limit": "512m", "pids_limit": 128, "nano_cpus": 1_000_000_000,
                   "security_opt": ["no-new-privileges:true"]}

HEADER = re.compile(r"^\s*(?:#|//)\s*(language|requires)\s*:\s*(.*?)\s*$", re.IGNORECASE)
LIBRARY = re.compile(r"^[A-Za-z0-9@][\w.+\-/@=<>~\[\]]*$")
USER_CODE_TASK = "run the code from the user's message"     # the task RUN_CODE_PROMPT names for code the user gave
# code in a message: a markdown fence or a line that starts like code
CODE = re.compile(r"```|^[ \t]*(?:def |class |import |from [\w.]+ import |#include|function |public |package |func |print\(|console\.log\()", re.M)
FENCE = re.compile(r"^```[^\n]*\n(.*?)(?:^```[ \t]*$|\Z)", re.DOTALL | re.MULTILINE)  # fences on their own lines

def strip_fences(reply: str) -> str:
    """the code of the reply: a <think> block dropped, the first markdown fence's content if there is one"""
    reply = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.DOTALL)
    match = FENCE.search(reply)
    return (match.group(1) if match else reply).strip("\n")


def parse_header(code: str) -> Tuple[str, List[str], str]:
    """the "# language: x" and "# requires: a, b" lines at the top: (language or "", libraries, code without them)"""
    language, libraries = "", []
    lines = code.split("\n")
    while lines and (not lines[0].strip() or HEADER.match(lines[0])):
        match = HEADER.match(lines.pop(0))
        if match and match.group(1).lower() == "language":
            language = match.group(2).lower()
        elif match:
            libraries += [lib for lib in re.split(r"[,\s]+", match.group(2)) if lib]
    return language, libraries, "\n".join(lines)


def build_call(reply: str, language: str = "") -> str:
    """the tool call line the harness builds around the model's code reply. the code goes in base64: it would break the
    one line json (quotes, braces, newlines) and extract_tool_calls. the header language wins over the directed one"""
    header_language, libraries, code = parse_header(strip_fences(reply))
    language = (header_language or language or "python").strip().lower()
    return json.dumps({"tool": "run_code", "language": ALIASES.get(language, language), "libraries": libraries,
                       "code": base64.b64encode(code.encode("utf-8")).decode("ascii")})


def clip(text: str, tail: bool = False) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_OUTPUT:
        return text
    return f"[... {len(text) - MAX_OUTPUT} characters cut]\n{text[-MAX_OUTPUT:]}" if tail \
        else f"{text[:MAX_OUTPUT]}\n[... {len(text) - MAX_OUTPUT} characters cut]"


def format_result(language: str, libraries: List[str], exit_code: int, stdout: str, stderr: str) -> str:
    """what the model gets back: exit code, stdout (start kept), stderr (end kept, that's where errors are)"""
    text = f"ran a {language} program" + (f" with {', '.join(libraries)}" if libraries else "") + f", exit code {exit_code}"
    text += f"\nSTDOUT:\n{clip(stdout) or '(empty)'}"
    if (stderr or "").strip():
        text += f"\nSTDERR:\n{clip(stderr, tail=True)}"
    return text


def run_in_sandbox(language: str, code: str, libraries: List[str], volume: SandboxVolume) -> Tuple[int, str, str]:
    """a fresh container for this one run with the contact's files (volume.session), removed when it ends. the docker
    daemon comes from the environment (DOCKER_HOST or /var/run/docker.sock)"""
    configs = dict(RUNTIME_CONFIGS) if libraries else {**RUNTIME_CONFIGS, "network_mode": "none"}
    with volume.session(configs, lang=language, skip_environment_setup=not libraries) as session:
        if language == "cpp" and libraries:     # llm sandbox runs apt-get install without update and -y
            installed = session.execute_command(f"timeout {INSTALL_TIMEOUT} sh -c 'apt-get update -qq && "
                                                f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {' '.join(libraries)}'")
            if installed.exit_code != 0:
                return installed.exit_code, "", f"installing {', '.join(libraries)} failed:\n{installed.stderr or installed.stdout}"
            libraries = []
        result = session.run(code, libraries=libraries or None, timeout=INSTALL_TIMEOUT if libraries else RUN_TIMEOUT)
        return result.exit_code, result.stdout, result.stderr


def run_call(call: Dict[str, Any], volume: SandboxVolume) -> Dict[str, Any]:
    """runs a built call with the contact's files: the base64 code decoded, checked and run.
    returns the tool result {"tool", "text"|"error"}"""
    language, libraries = call.get("language", "python"), call.get("libraries") or []
    code = base64.b64decode(call.get("code", "")).decode("utf-8")
    if not code.strip():
        return {"tool": "run_code", "error": "no code was written"}
    if language not in LANGUAGES:
        return {"tool": "run_code", "error": f"{language} is not supported, only {', '.join(LANGUAGES)}"}
    if language == "java" and libraries:
        return {"tool": "run_code", "error": f"java can't install libraries ({', '.join(libraries)}), "
                                             "only its standard library works. Nothing ran."}
    bad = [lib for lib in libraries if not LIBRARY.match(lib)]
    if bad or len(libraries) > MAX_LIBRARIES:
        return {"tool": "run_code", "error": f"invalid library list {libraries}, at most {MAX_LIBRARIES} plain package names. Nothing ran."}
    try:
        blocked = volume.write_block()      # the program sees the files read only
        exit_code, stdout, stderr = run_in_sandbox(language, code, libraries, volume)
    except Exception as e:
        if type(e).__name__ == "SandboxTimeoutError":
            return {"tool": "run_code", "error": f"the program was stopped, it ran longer than "
                                                 f"{INSTALL_TIMEOUT if libraries else RUN_TIMEOUT} seconds"}
        logger.error(f"sandbox run failed: {repr(e)}")
        return {"tool": "run_code", "error": f"the code could not be run: {type(e).__name__}: {str(e)[:300]}"}
    text = format_result(language, libraries, exit_code, stdout, stderr)
    return {"tool": "run_code", "text": text + (f"\nNOTE: the files are read only: {blocked}" if blocked else "")}


class RunCodeTool(Tool):
    """writes a one file program for the directed task (own llm call, the reply is only code) and runs it in a
    fresh llm sandbox container with the contact's files. the harness builds the call json with the code in base64"""
    description = prompts.RUN_CODE_DESCRIPTION
    sequential = True
    fixable = True
    thresholds = (0.65, 0.7)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user want to see the output of running code?",
        "Does this message ask to check or confirm a number or formula before using it?",
        "Does this message ask to verify, test, benchmark, reproduce or prototype something by running code or computing numbers?",
        "Does this message ask to debug or reproduce an error by running code?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "run_code"

    @classmethod
    def problems(cls, result: Dict[str, Any]) -> List[str]:
        """a program that could not run or ended with an exit code other than 0 (format_result)"""
        if "error" in result:
            return [f"run_code: {result['error']}"]
        return [f"the {language} program of run_code ended with exit code {code}"
                for language, code in re.findall(r"^ran an? (\S+) program.*?, exit code (-?\d+)$", result.get("text") or "", re.M) if code != "0"]

    def conversation(self) -> str:
        """the latest messages the code writer sees (pasted code stays in them, not in json)"""
        messages = self.db.get_messages_by_conversation(self.get_conversation_id(), CONTEXT_MESSAGES) or []
        return "\n\n".join(f"{m['role']}: {(m['content'] or '')[:MAX_MESSAGE_CHARS]}"
                           for m in messages if m["role"] in ("user", "assistant") and m["content"])

    def without_code(self, conversation: str) -> bool:
        """the call is to run the user's code (USER_CODE_TASK), but the conversation has none: the prompt's example copied"""
        return USER_CODE_TASK in str(self.tool_call.get("task") or "").lower() and not CODE.search(conversation)

    def write_code(self, conversation: str) -> str:
        """the code writing llm call: the latest messages (conversation()) and the task"""
        task = self.tool_call.get("task") or "do what the user's latest message asks"
        query = f"CONVERSATION (latest last):\n{conversation}\n\nTASK:\n{task}"
        language = self.tool_call.get("language")
        if language:
            query += f"\n\nLANGUAGE: {language}"
        return self.infrastructure.chat(
            messages=[{"role": "system", "content": prompts.RUN_CODE_WRITER_PROMPT.format(run_timeout=RUN_TIMEOUT, files=MOUNT_PATH, projects=f"{MOUNT_PATH}/{PROJECTS}", workdir=SandboxVolume.workdir(self.get_conversation_id()))}, {"role": "user", "content": query}],
            temperature=0.2,
            seed=random.randint(0, 100000),
            max_new_tokens=self.infrastructure.long_reply_tokens(),
            timeout=self.tool_call.get("llm_timeout")     # set by agent jobs, None in chat (240 s)
        ) or ""

    def execute(self) -> None:
        conversation = self.conversation()
        if self.without_code(conversation):
            logger.warning(f"run_code: no code in the conversation to run, nothing ran: {self.tool_call.get('task')}")
            self.add_result({"tool": self.name(), "error": prompts.RUN_CODE_NO_CODE_PART})
            return
        MessageQueue().send_status_message("writing code")
        reply = self.write_code(conversation)
        if not reply.strip():
            result = {"tool": self.name(), "error": "no code was written, the language model gave no reply"}
        else:
            call = build_call(reply, str(self.tool_call.get("language") or ""))
            logger.debug(f"run_code call: {call}")
            logger.debug(f"code:\n{reply}")
            MessageQueue().send_status_message("running code")
            result = run_call(json.loads(call), SandboxVolume(self.get_user_id(), self.contact_id))
        self.add_result(result)

    @classmethod
    def prompt(cls) -> str:
        return prompts.RUN_CODE_PROMPT
