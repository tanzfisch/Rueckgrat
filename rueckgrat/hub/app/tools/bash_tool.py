import re
import time
from typing import Dict, Any, List, Optional, Tuple
from .tool import Tool
from . import prompts
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, PROJECTS, DOCUMENTS, IMAGES
from app.utils.sandbox_container import SandboxContainer, CPUS, MEMORY_GB

from app.common import get_logger, MessageQueue
logger = get_logger()

COMMAND_TIMEOUT = 120       # seconds, a git clone or pip install needs a while
MAX_OUTPUT = 4000           # characters of stdout and of stderr for the model
MAX_COMMAND_ECHO = 300      # characters of the command repeated in its result
# the terminal stays open per conversation: the folder, the exported variables (an activated venv) and the shell
# functions of the conversation's last command are restored before the next one, a new conversation starts in its
# workdir. kept with the files (SandboxVolume.shell_state), .cache is not in a zip. {state}, {workdir}: of the conversation
RESTORE = ('S={state}; mkdir -p "$S"\n'
           '[ -f "$S/env" ] && . "$S/env" 2>/dev/null; [ -f "$S/functions" ] && . "$S/functions" 2>/dev/null\n'
           '{{ [ -s "$S/cwd" ] && cd "$(cat "$S/cwd")" 2>/dev/null; }} || {{ mkdir -p {workdir} && cd {workdir}; }}\n'
           'trap \'code=$?; pwd > "$S/cwd"; export -p | grep -v -E "^declare -x (PWD|OLDPWD|SHLVL|HOSTNAME|_)=" > "$S/env"; '
           'declare -p ${{!_OLD_VIRTUAL_*}} >> "$S/env" 2>/dev/null; declare -f > "$S/functions"; exit $code\' EXIT\n')


def clip(text: str, tail: bool = False) -> str:
    """text up to MAX_OUTPUT characters: its start, or its end (tail, where the errors are)"""
    text = (text or "").strip()
    if len(text) <= MAX_OUTPUT:
        return text
    return f"[... {len(text) - MAX_OUTPUT} characters cut]\n{text[-MAX_OUTPUT:]}" if tail \
        else f"{text[:MAX_OUTPUT]}\n[... {len(text) - MAX_OUTPUT} characters cut]"


class BashTool(Tool):
    """runs one bash command in the contact's sandbox container (SandboxContainer: git, curl, python, C and C++ builds,
    sudo), as SANDBOX_USER, with network, in the contact's persistent files (SandboxVolume, shared by all its
    conversations), each with its own timeout and result, a failing command does not stop the next. the files and
    the container's installs carry over, and like an open terminal per conversation the folder, exported variables and
    functions (RESTORE), running processes do not"""
    description = prompts.BASH_DESCRIPTION
    sequential = True
    thresholds = (0.6, 0.75)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the message ask to copy, move, rename, delete, list or unzip files or folders that already exist?",
        "Does the message ask to run git, like clone, pull or status?",
        "Does the message ask to install a package with pip, apt or npm?",
        "Does the user ask to see which processes run or how much memory or disk is used?",
        "Does the user ask to find files or to search for a word in files?",
        "Does the message ask to change the permissions of a file?",
        "Does the message ask to search inside files or count the lines of a file?",
        "Does the message ask to make a new directory with mkdir?",
    ]

    @classmethod
    def name(cls) -> str:
        return "bash"

    # a plain listing: "ls -la", "ls .", "ls <workdir>", "cd <workdir> && ls -la", nothing chained, piped or substituted
    LISTING = re.compile(r"(?:cd\s+(?P<folder>[\w./~-]+)\s*&&\s*)?ls(?:\s+-[a-zA-Z]+)*(?:\s+(?P<path>[\w./~-]+))?")

    @classmethod
    def looks_around(cls, call: Dict[str, Any], conversation_id: int) -> bool:
        """a plain ls of the conversation's workdir (LISTING): read only, where a worker looks for the files of the
        steps before"""
        match = cls.LISTING.fullmatch(str(call.get("command") or "").strip())
        if not match:
            return False
        workdir = SandboxVolume.workdir(conversation_id)
        return match["folder"] in (None, workdir, f"{workdir}/") and match["path"] in (None, ".", "./", workdir, f"{workdir}/")

    def run(self, command: str) -> Dict[str, Any]:
        """the tool result {"tool", "text"|"error"} of one command"""
        try:
            restore = RESTORE.format(state=SandboxVolume.shell_state(self.get_conversation_id()),
                                     workdir=SandboxVolume.workdir(self.get_conversation_id()))
            started = time.monotonic()
            code, stdout, stderr = SandboxContainer(SandboxVolume(self.get_user_id(), self.contact_id)).run(
                restore + command, COMMAND_TIMEOUT)
            stopped = time.monotonic() - started >= COMMAND_TIMEOUT - 1
        except Exception as e:
            logger.error(f"bash failed: {repr(e)}")
            return {"tool": self.name(), "error": f"the command could not be run: {type(e).__name__}: {str(e)[:300]}"}
        # the command leads: a later round (attaching the files) and the reply see what each call did
        echo = command if len(command) <= MAX_COMMAND_ECHO else f"{command[:MAX_COMMAND_ECHO]} [...]"
        text = f"$ {echo}\nexit code {code}" + (f" (stopped after {COMMAND_TIMEOUT} seconds)" if code == 124 and stopped else "")
        text += f"\nSTDOUT:\n{clip(stdout) or '(empty)'}"
        if stderr.strip():
            text += f"\nSTDERR:\n{clip(stderr, tail=True)}"
        return {"tool": self.name(), "text": text}

    def execute(self) -> None:
        command = str(self.tool_call.get("command") or "").strip()
        if not command:
            self.add_result({"tool": self.name(), "error": "no command given"})
            return
        logger.debug(f"bash: {command}")
        MessageQueue().send_status_message("running bash")
        self.add_result(self.run(command))

    @classmethod
    def prompt(cls, workdir: str = f"{MOUNT_PATH}/workdir/<conversation>", projects: str = prompts.BASH_PROJECTS_UNKNOWN_PART,
               loop: bool = False) -> str:
        """loop: a worker's loop (Tool.prompt_for), else a setup that writes all its calls at once"""
        return prompts.BASH_PROMPT.format(files=MOUNT_PATH, timeout=COMMAND_TIMEOUT, workdir=workdir, projects=projects,
                                          cpus=CPUS, memory=MEMORY_GB,
                                          project_dir=f"{MOUNT_PATH}/{PROJECTS}", documents=f"{MOUNT_PATH}/{DOCUMENTS}",
                                          images=f"{MOUNT_PATH}/{IMAGES}",
                                          turns=prompts.BASH_LOOP_PART if loop else prompts.BASH_ONE_TURN_PART)

    @classmethod
    def prompt_for(cls, user_id: int, contact_id: int, conversation_id: int, loop: bool = False) -> str:
        """the prompt with the conversation's workdir and the contact's projects (SandboxVolume.projects): name and the
        first line of its PROJECT.md each"""
        try:
            projects = SandboxVolume(user_id, contact_id).projects()
        except Exception as e:
            logger.warning(f"projects of contact {contact_id} not listed {repr(e)}")
            projects = None
        return cls.prompt(SandboxVolume.workdir(conversation_id), cls.projects_text(projects), loop)

    @staticmethod
    def projects_text(projects: Optional[List[Tuple[str, str]]]) -> str:
        """the projects (SandboxVolume.projects) one line each: folder and the first line of its PROJECT.md. None: they
        could not be read"""
        if projects is None:
            return prompts.BASH_PROJECTS_UNKNOWN_PART
        return "\n".join(prompts.BASH_PROJECT_LINE.format(name=name, summary=summary or "no PROJECT.md")
                         for name, summary in projects) or prompts.BASH_NO_PROJECTS_PART
