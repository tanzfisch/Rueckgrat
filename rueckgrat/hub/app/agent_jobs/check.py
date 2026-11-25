"""
#230 a job step's done-check: one shell command, run in the step's folder after its worker ended. only it decides
whether the step is done (Controller), never what the worker says. it runs in a clean shell: no saved shell state, no
exported variables and an empty HOME, so a stand-in for sudo or a package installed outside the project does not pass.
"""
import re
import shlex
from typing import Dict, Any, Tuple

from .agent_job import JOB_LLM_TIMEOUT
from .worker import EXIT_CODE, RESULT_CHARS, clip

from app.common import get_logger
logger = get_logger()

# the file names a goal names, the default check tests that they are there (.js only in FILE_TASK: "Node.js" is a name)
EXTENSIONS = (r"py|ipynb|ts|tsx|jsx|html?|css|scss|md|txt|json|ya?ml|toml|ini|cfg|sh|csv|tsv|xml|svg|png|jpe?g|gif|webp|bmp|"
              r"mp3|ogg|wav|c|cc|cpp|h|hpp|rs|go|java|kt|rb|php|lua|sql|pdf|docx?|xlsx?")
NAMED_FILE = re.compile(rf"(?<![\w./~-])((?:[\w-]+/)*[\w-]+\.(?:{EXTENSIONS}))\b", re.IGNORECASE)
# a check never installs or changes the system and never works outside its folder
FORBIDDEN = re.compile(r"(?<![\w.-])(?:sudo|su|apt|apt-get|dpkg|pip3? install|python3? -m pip install|npm (?:i|install)|/tmp)(?![\w-])")
CLEAN_PATH = "/usr/local/bin:/usr/bin:/bin"


class Check:
    """a step's done-check in its folder (absolute): the plan's command when it is allowed, else the default (the files
    the goal names are there and not empty), "" when there is none: then the worker's end decides (Controller)"""

    def __init__(self, command: str, goal: str, folder: str):
        command = str(command or "").strip()
        self._planned = command
        self._command = command if command and self.allowed(command) else self.default(goal)
        self._folder = folder

    def command(self) -> str:
        return self._command

    def folder(self) -> str:
        return self._folder

    def replaced(self) -> bool:
        """the plan's command was not allowed, the default runs instead"""
        return bool(self._planned) and self._planned != self._command

    @staticmethod
    def allowed(command: str) -> bool:
        return not FORBIDDEN.search(command or "")

    @staticmethod
    def default(goal: str) -> str:
        """test -s of every file the goal names, "" for none"""
        return " && ".join(f"test -s {shlex.quote(name)}" for name in dict.fromkeys(NAMED_FILE.findall(goal or "")))

    def script(self) -> str:
        """the command as bash runs it: its folder made and entered, a clean environment with an empty HOME, removed after"""
        folder = shlex.quote(self._folder)
        return (f"mkdir -p {folder} && (h=$(mktemp -d); cd {folder} && env -i HOME=\"$h\" PATH={CLEAN_PATH} LANG=C.UTF-8 "
                f"bash -c {shlex.quote(self._command)}; c=$?; rm -rf \"$h\"; exit $c)")

    def run(self, tool_context: Dict[str, Any]) -> Tuple[bool, str]:
        """(passed, its output): exit code 0, or 124 when a timeout stopped a program that was still running. (True, "")
        without a command"""
        if not self._command:
            return True, ""
        registry = tool_context["tool_registry"]
        try:
            results = registry.execute(tool_context["user_id"], tool_context["contact_id"], tool_context["conversation_id"],
                                       {"tool": "bash", "command": self.script(), "llm_timeout": JOB_LLM_TIMEOUT, "background": True}) or {}
            result = results.get("bash") or {}
        except Exception as e:
            logger.error(f"check `{self._command}` failed {repr(e)}")
            return False, repr(e)
        text = str(result.get("error") or result.get("text") or "")
        match = EXIT_CODE.search(text)
        passed = bool(match) and not match.group(2) and int(match.group(1)) in (0, 124)
        output = text.split("\n", 1)[1] if text.startswith("$ ") and "\n" in text else text    # without the script it ran
        return passed, clip(output, RESULT_CHARS // 4)
