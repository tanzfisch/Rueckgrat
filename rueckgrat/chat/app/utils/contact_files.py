"""the sandbox files of one contact: one volume for all its conversations, what the AI wrote with bash,
write_file or text_to_speech. the hub serves them by a conversation of the contact (/conversations/{id}/files), any of
its conversations shows the same files"""
from .hub import Hub


class ContactFiles:
    def __init__(self, contact_id: int, conversation_id: int, name: str = ""):
        """conversation_id: one of the contact's conversations, the hub's way to the files. name: the contact's, for a zip"""
        self._contact_id = contact_id
        self._conversation_id = conversation_id
        self._name = name

    @property
    def key(self):
        """the same key: the same files (a panel keeps the folder it showed)"""
        return self._contact_id

    @property
    def zip_name(self) -> str:
        """the name of a zip of all the files, without .zip"""
        name = "_".join(self._name.split()).lower()
        return f"{name}_files" if name else f"contact_{self._contact_id}_files"

    def entries(self, path: str = "") -> list | None:
        """one folder: [{"name", "path", "type", "size", "modified"}], None on an error"""
        return Hub.get_conversation_files(self._conversation_id, path)

    def file(self, path: str) -> bytes | None:
        return Hub.get_conversation_file(self._conversation_id, path)

    def zip(self, path: str = "", exclude: bool = True) -> bytes | None:
        """a folder ("" all) as a zip. exclude: without .git, caches, packages"""
        return Hub.get_conversation_files_zip(self._conversation_id, path, exclude)
