import re
import shlex
import time
from typing import Dict, Any, List
from .tool import Tool
from .code_tool import RUNTIME_CONFIGS, clip
from . import prompts
from app.utils.conversation_volume import ConversationVolume, MOUNT_PATH, SANDBOX_USER

from app.common import get_logger, MessageQueue
logger = get_logger()

COMMAND_TIMEOUT = 120       # seconds, a git clone or pip install needs a while
MAX_COMMAND_ECHO = 300      # characters of the command repeated in its result
# the terminal stays open: the folder, the exported variables (an activated venv) and the shell functions of the
# conversation's last command are restored before the next one. kept with the files, .cache is not in a zip
SHELL_STATE = f"{MOUNT_PATH}/.cache/rueckgrat/shell"
RESTORE = (f'S={SHELL_STATE}; mkdir -p "$S"\n'
           '[ -f "$S/env" ] && . "$S/env" 2>/dev/null; [ -f "$S/functions" ] && . "$S/functions" 2>/dev/null\n'
           f'cd "$(cat "$S/cwd" 2>/dev/null)" 2>/dev/null || cd {MOUNT_PATH}\n'
           'trap \'code=$?; pwd > "$S/cwd"; export -p | grep -v -E "^declare -x (PWD|OLDPWD|SHLVL|HOSTNAME|_)=" > "$S/env"; '
           'declare -p ${!_OLD_VIRTUAL_*} >> "$S/env" 2>/dev/null; declare -f > "$S/functions"; exit $code\' EXIT\n')
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
    in the conversation's persistent files (ConversationVolume). the calls of one round share one container (sharing),
    each with its own timeout and result, a failing command does not stop the next. the files carry over, and like an
    open terminal the folder, exported variables and functions (SHELL_STATE), running processes do not"""
    description = prompts.BASH_DESCRIPTION
    sequential = True
    question = [
        "Does this message ask to create, edit, list, read or delete files?",
        "Does this message ask to run a shell command or a command line tool?",
        "Does this message ask to clone, inspect or change a git repository?",
        "Does this message ask to continue working on files from earlier in the conversation?",
        "Does this message ask to create a program, a script or a software project?",
    ]

    @classmethod
    def name(cls) -> str:
        return "bash"

    @classmethod
    def sharing(cls):
        return ConversationVolume.sharing()

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
            with ConversationVolume(self.user_id, self.conversation_id).session(configs, lang="python",
                                                                               skip_environment_setup=True) as session:
                started = time.monotonic()
                result = session.execute_command(f"timeout {COMMAND_TIMEOUT} bash -c {shlex.quote(RESTORE + command)}",
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
    def prompt(cls) -> str:
        return prompts.BASH_PROMPT.format(files=MOUNT_PATH, timeout=COMMAND_TIMEOUT)
