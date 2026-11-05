import base64
import json
import random
import re
from typing import Dict, Any, List, Tuple
from .tool import Tool, ToolCategory

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
FENCE = re.compile(r"^```[^\n]*\n(.*?)(?:^```[ \t]*$|\Z)", re.DOTALL | re.MULTILINE)  # fences on their own lines

CODE_PROMPT = f"""You write one complete program for the task below. It runs once in a fresh sandbox, what it prints comes back to you.

Reply with ONLY the source code of the program as plain text: no JSON, no explanation, no markdown fences.

Rules:
- One single file. Print every result to stdout, the program gets no input.
- Python, unless the task or the user asks for another language: javascript, cpp, java or go.
- Header lines at the very top, only when needed, always with # (they are removed before the program runs):
# language: cpp
# requires: numpy, pandas
- "language" when it is not python. "requires" lists packages to install first: pip for python, npm for javascript, apt for cpp, go modules for go. java can't install packages, use only its standard library.
- When the user gave code to run, reply with that code unchanged (add header lines if it needs packages).
- It must finish within {RUN_TIMEOUT} seconds. Keep the output short."""


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


def run_in_sandbox(language: str, code: str, libraries: List[str]) -> Tuple[int, str, str]:
    """a fresh container for this one run (SandboxSession), removed when it ends. the docker daemon comes from the
    environment (DOCKER_HOST or /var/run/docker.sock). keep_template: the language image stays, no pull per run"""
    from llm_sandbox import SandboxSession  # only needed here, the hub runs without docker access too
    configs = dict(RUNTIME_CONFIGS) if libraries else {**RUNTIME_CONFIGS, "network_mode": "none"}
    with SandboxSession(lang=language, keep_template=True, runtime_configs=configs, encoding_errors="replace",
                        skip_environment_setup=not libraries) as session:
        if language == "cpp" and libraries:     # llm sandbox runs apt-get install without update and -y
            installed = session.execute_command(f"timeout {INSTALL_TIMEOUT} sh -c 'apt-get update -qq && "
                                                f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {' '.join(libraries)}'")
            if installed.exit_code != 0:
                return installed.exit_code, "", f"installing {', '.join(libraries)} failed:\n{installed.stderr or installed.stdout}"
            libraries = []
        result = session.run(code, libraries=libraries or None, timeout=INSTALL_TIMEOUT if libraries else RUN_TIMEOUT)
        return result.exit_code, result.stdout, result.stderr


def run_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """runs a built call: the base64 code decoded, checked and run. returns the tool result {"tool", "text"|"error"}"""
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
        exit_code, stdout, stderr = run_in_sandbox(language, code, libraries)
    except Exception as e:
        if type(e).__name__ == "SandboxTimeoutError":
            return {"tool": "run_code", "error": f"the program was stopped, it ran longer than "
                                                 f"{INSTALL_TIMEOUT if libraries else RUN_TIMEOUT} seconds"}
        logger.error(f"sandbox run failed: {repr(e)}")
        return {"tool": "run_code", "error": f"the code could not be run: {type(e).__name__}: {str(e)[:300]}"}
    return {"tool": "run_code", "text": format_result(language, libraries, exit_code, stdout, stderr)}


class RunCodeTool(Tool):
    """writes a one file program for the directed task (own llm call, the reply is only code) and runs it in a
    fresh llm sandbox container. the harness builds the call json with the code in base64"""
    category = ToolCategory.MATH
    description = "writes a small program and runs it in a sandbox container, returns its output"
    # laya, 0.5: user asks to run code, or the message (a chat message or a worker's task) needs a check the ai runs on
    # its own: verify, debug (reproduce an error), benchmark, explore an api, validate math before a plan, prototype.
    # 41 positives, 40 negatives: run requests 4/4, debug 6/6, validate 6/6, prototype 6/6, benchmark 5/6, explore 5/6,
    # bare math questions ("is 2^61-1 prime?", "100th digit of pi") only 3/9. false positives 2/40 ("write me a python
    # function ...", "write a regex ..."). the first question alone: 22/41 hits, 1/40 false positives
    question = [
        "Does the user ask you to run, execute or test code?",
        "Does this message ask to check or confirm a number or formula before using it?",
        "Does this message ask to verify, test, benchmark, reproduce or prototype something with code or numbers?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "run_code"

    def write_code(self) -> str:
        """the code writing llm call: latest messages (pasted code stays in them, not in json) and the task"""
        messages = self.db.get_messages_by_conversation(self.conversation_id, CONTEXT_MESSAGES) or []
        conversation = "\n\n".join(f"{m['role']}: {(m['content'] or '')[:MAX_MESSAGE_CHARS]}"
                                   for m in messages if m["role"] in ("user", "assistant") and m["content"])
        task = self.tool_call.get("task") or "do what the user's latest message asks"
        query = f"CONVERSATION (latest last):\n{conversation}\n\nTASK:\n{task}"
        language = self.tool_call.get("language")
        if language:
            query += f"\n\nLANGUAGE: {language}"
        return self.infrastructure.chat(
            messages=[{"role": "system", "content": CODE_PROMPT}, {"role": "user", "content": query}],
            temperature=0.2,
            seed=random.randint(0, 100000),
            max_new_tokens=4096,
            timeout=self.tool_call.get("llm_timeout")     # set by agent jobs, None in chat (240 s)
        ) or ""

    def execute(self) -> None:
        MessageQueue().send_status_message("writing code")
        reply = self.write_code()        
        if not reply.strip():
            result = {"tool": self.name(), "error": "no code was written, the language model gave no reply"}
        else:
            call = build_call(reply, str(self.tool_call.get("language") or ""))
            logger.debug(f"run_code call: {call}")
            logger.debug(f"code:\n{reply}")
            MessageQueue().send_status_message("running code")
            result = run_call(json.loads(call))
        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
RUN_CODE:
Use when the user asks you to run or execute code, or to work something out with a program: exact results with big numbers, simulations, data processing, checking that code works. A separate step writes one program file for your task and runs it in a fresh sandbox, you get its output, errors and exit code back.
You may also use it on your own when an exact check is better than guessing:
- verify a calculation, a count or an idea (primes, digits, dates, regex matches)
- debug: reproduce an error in isolation to find its cause
- benchmark: compare snippets for speed or output
- explore an unfamiliar function or library by trying it
- validate math or logic before you rely on it in a longer plan
- prototype a small piece to see if an approach works before using it
Do not use it when the user only wants to see or discuss code, or for simple arithmetic (calculator).

Parameters:
- task (string, required): what the program must do and print, with all the values it needs. When the user gave code to run, write "run the code from the user's message", do not copy the code here.
- language (string, optional): "python" (default), "javascript", "cpp", "java" or "go"

Examples:
{"tool": "run_code", "task": "compute the 50th Fibonacci number and print it"}
{"tool": "run_code", "task": "run the code from the user's message", "language": "javascript"}
"""
