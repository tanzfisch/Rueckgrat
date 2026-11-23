from .tool import Tool
from . import prompts
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH
from app.utils.sandbox_container import SandboxContainer

from app.common import get_logger, MessageQueue
logger = get_logger()

WHATS = ("system", "files", "all")    # the first without a what


class ResetSandboxTool(Tool):
    """resets the contact's sandbox: system (the default) a fresh container from the image (installs, their record and
    running processes go, the files stay, SandboxContainer.reset: made again by the next command), files, only when the
    user asks, brings the files back to the hub's backup (SandboxVolume.restore, the replaced files kept in the backup's
    safety copy), all both"""
    description = prompts.RESET_SANDBOX_DESCRIPTION
    sequential = True           # in its round's order with the calls that use the files
    offered_with = ("bash",)    # no laya question: offered (optional) with the commands it resets

    @classmethod
    def name(cls) -> str:
        return "reset_sandbox"

    def execute(self) -> None:
        what = str(self.tool_call.get("what") or WHATS[0]).strip().lower()
        if what not in WHATS:
            self.add_result({"tool": self.name(), "error": prompts.RESET_SANDBOX_WHAT_PART.format(what=what)})
            return
        MessageQueue().send_status_message("resetting the sandbox")
        volume = SandboxVolume(self.get_user_id(), self.contact_id)
        container = SandboxContainer(volume)
        try:
            if what != "system":
                container.stop_processes()
                volume.restore()
            if what == "files":
                container.record()  # the restored files bring an older record of the packages
            else:
                container.reset()
        except FileNotFoundError:
            self.add_result({"tool": self.name(), "error": prompts.RESET_SANDBOX_NO_BACKUP_PART})
            return
        except Exception as e:
            logger.error(f"reset_sandbox {what} failed: {repr(e)}")
            self.add_result({"tool": self.name(), "error": f"the sandbox could not be reset: {type(e).__name__}: {str(e)[:300]}"})
            return
        self.add_result({"tool": self.name(), "text": prompts.RESET_SANDBOX_DONE_PARTS[what].format(files=MOUNT_PATH)})

    @classmethod
    def prompt(cls) -> str:
        return prompts.RESET_SANDBOX_PROMPT.format(files=MOUNT_PATH)
