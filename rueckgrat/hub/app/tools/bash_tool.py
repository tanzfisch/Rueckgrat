import re
import shlex
import time
from typing import Dict, Any, List
from .tool import Tool
from .code_tool import RUNTIME_CONFIGS, clip
from . import prompts
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, SANDBOX_USER, PROJECTS, DOCUMENTS, IMAGES

from app.common import get_logger, MessageQueue
logger = get_logger()

COMMAND_TIMEOUT = 120       # seconds, a git clone or pip install needs a while
MAX_COMMAND_ECHO = 300      # characters of the command repeated in its result
# the terminal stays open per conversation: the folder, the exported variables (an activated venv) and the shell
# functions of the conversation's last command are restored before the next one, a new conversation starts in its
# workdir. kept with the files (SandboxVolume.shell_state), .cache is not in a zip. {state}, {workdir}: of the conversation
RESTORE = ('S={state}; mkdir -p "$S"\n'
           '[ -f "$S/env" ] && . "$S/env" 2>/dev/null; [ -f "$S/functions" ] && . "$S/functions" 2>/dev/null\n'
           '{{ [ -s "$S/cwd" ] && cd "$(cat "$S/cwd")" 2>/dev/null; }} || {{ mkdir -p {workdir} && cd {workdir}; }}\n'
           'trap \'code=$?; pwd > "$S/cwd"; export -p | grep -v -E "^declare -x (PWD|OLDPWD|SHLVL|HOSTNAME|_)=" > "$S/env"; '
           'declare -p ${{!_OLD_VIRTUAL_*}} >> "$S/env" 2>/dev/null; declare -f > "$S/functions"; exit $code\' EXIT\n')
# the files home: git config and pip install --user stay with the files. a fixed git author, git commit refuses without one
ENVIRONMENT = {
    "HOME": MOUNT_PATH,
    "PATH": f"{MOUNT_PATH}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "GIT_AUTHOR_NAME": "Rueckgrat", "GIT_AUTHOR_EMAIL": "sandbox@rueckgrat.local",
    "GIT_COMMITTER_NAME": "Rueckgrat", "GIT_COMMITTER_EMAIL": "sandbox@rueckgrat.local",
}


class BashTool(Tool):
    """runs one bash command in a sandbox container (python image: git, curl, python), as SANDBOX_USER, with network,
    in the contact's persistent files (SandboxVolume, shared by all its conversations). the calls of one round share one
    container (sharing), each with its own timeout and result, a failing command does not stop the next. the files carry
    over, and like an open terminal per conversation the folder, exported variables and functions (RESTORE), running
    processes do not"""
    description = prompts.BASH_DESCRIPTION
    sequential = True
    fixable = True
    thresholds = (0.6, 0.65)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
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

    @classmethod
    def sharing(cls):
        return SandboxVolume.sharing()

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

    @classmethod
    def problems(cls, result: Dict[str, Any]) -> List[str]:
        """each command of the result (merged results: one block per command, see run) that ended with an exit code other than 0"""
        if "error" in result:
            return [f"bash: {result['error']}"]
        # 124 of a command's own timeout (not the tool's): a program that runs until it is stopped ran fine
        return [f"bash `{command.splitlines()[0][:150]}` ended with exit code {code}"
                for command, code, rest in re.findall(r"^\$ (.*?)\nexit code (-?\d+)([^\n]*)", result.get("text") or "", re.M | re.S)
                if code != "0" and not (code == "124" and "stopped after" not in rest and "timeout " in command)]

    def run(self, command: str) -> Dict[str, Any]:
        """the tool result {"tool", "text"|"error"} of one command"""
        configs = {**RUNTIME_CONFIGS, "user": SANDBOX_USER, "environment": dict(ENVIRONMENT)}
        try:
            restore = RESTORE.format(state=SandboxVolume.shell_state(self.get_conversation_id()),
                                     workdir=SandboxVolume.workdir(self.get_conversation_id()))
            with SandboxVolume(self.get_user_id(), self.contact_id).session(configs, lang="python",
                                                                      skip_environment_setup=True) as session:
                started = time.monotonic()
                result = session.execute_command(f"timeout {COMMAND_TIMEOUT} bash -c {shlex.quote(restore + command)}",
                                                 workdir=MOUNT_PATH)
                stopped = time.monotonic() - started >= COMMAND_TIMEOUT - 1
        except Exception as e:
            logger.error(f"bash failed: {repr(e)}")
            return {"tool": self.name(), "error": f"the command could not be run: {type(e).__name__}: {str(e)[:300]}"}
        # the command leads: a later round (attaching the files) and the reply see what each call did
        echo = command if len(command) <= MAX_COMMAND_ECHO else f"{command[:MAX_COMMAND_ECHO]} [...]"
        text = f"$ {echo}\nexit code {result.exit_code}" + \
               (f" (stopped after {COMMAND_TIMEOUT} seconds)" if result.exit_code == 124 and stopped else "")
        text += f"\nSTDOUT:\n{clip(result.stdout) or '(empty)'}"
        if (result.stderr or "").strip():
            text += f"\nSTDERR:\n{clip(result.stderr, tail=True)}"
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
    def prompt(cls, workdir: str = f"{MOUNT_PATH}/workdir/<conversation>", projects: str = prompts.BASH_PROJECTS_UNKNOWN_PART) -> str:
        return prompts.BASH_PROMPT.format(files=MOUNT_PATH, timeout=COMMAND_TIMEOUT, workdir=workdir, projects=projects,
                                          project_dir=f"{MOUNT_PATH}/{PROJECTS}", documents=f"{MOUNT_PATH}/{DOCUMENTS}",
                                          images=f"{MOUNT_PATH}/{IMAGES}")

    @classmethod
    def prompt_for(cls, user_id: int, contact_id: int, conversation_id: int) -> str:
        """the prompt with the conversation's workdir and the contact's projects (SandboxVolume.projects): name and the
        first line of its PROJECT.md each"""
        try:
            projects = SandboxVolume(user_id, contact_id).projects()
            listed = "\n".join(prompts.BASH_PROJECT_LINE.format(name=name, summary=summary or "no PROJECT.md")
                                for name, summary in projects) or prompts.BASH_NO_PROJECTS_PART
        except Exception as e:
            logger.warning(f"projects of contact {contact_id} not listed {repr(e)}")
            listed = prompts.BASH_PROJECTS_UNKNOWN_PART
        return cls.prompt(SandboxVolume.workdir(conversation_id), listed)
