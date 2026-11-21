"""#193 #225 the contacts' sandbox files (SandboxVolume) as a network drive for the user: HUB_FILE_SHARE picks how,
webdav (SandboxDav, served by the hub) or smb (SandboxSmb, the hub keeps the smb service's users and shares), none or
unset: no share. what both do is here:

  the folders     one per contact of the user, "<name> (<id>)" (folder_name), the contact's files as the AI sees them
                  under /home
  the login       the hub's user name and password
  connecting      connect: each contact's folder's address, the app's network settings show it
  excluded names  HUB_FILE_SHARE_EXCLUDE (the installer writes it; unset or empty: EXCLUDED): virtual environments,
                  caches and installed packages work only where they were made (their paths, their python) and walking
                  them over the network is slow. a file or folder of such a name, at any depth, is not shared

the AI writes the files while the user has them open: the user knows when the AI works on them"""
import os
import re
from typing import Callable, Optional
from urllib.parse import urlsplit

KIND_ENV = "HUB_FILE_SHARE"         # webdav or smb, anything else: no share
KINDS = ("webdav", "smb")
EXCLUDE_ENV = "HUB_FILE_SHARE_EXCLUDE"     # comma separated names not shared, unset or empty: EXCLUDED
# the hub's own like its other settings' defaults (the installer offers its HUB_FILE_SHARE_EXCLUDE_DEFAULT, the same list)
EXCLUDED = (".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
            ".gradle", ".cache")
_FOLDER_ID = re.compile(r"\((\d+)\)$")
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


class FileShare:
    TITLE = ""      # the share's name for the user

    def __init__(self):
        self._db = None
        self._verify: Optional[Callable[[str, str], Optional[int]]] = None
        self._excluded = self.excluded_names()

    @staticmethod
    def kind() -> str:
        """HUB_FILE_SHARE: webdav, smb or none"""
        kind = os.environ.get(KIND_ENV, "").strip().lower()
        return kind if kind in KINDS else "none"

    @staticmethod
    def excluded_names() -> frozenset[str]:
        """the names not shared: HUB_FILE_SHARE_EXCLUDE (comma separated), unset or empty: EXCLUDED"""
        given = os.environ.get(EXCLUDE_ENV, "").strip()
        names = (name.strip() for name in given.split(",")) if given else EXCLUDED
        return frozenset(name for name in names if name and "/" not in name and name not in (".", ".."))

    def excludes(self) -> frozenset[str]:
        return self._excluded

    def excluded(self, path: str) -> bool:
        """whether path (in the share) is or is in an excluded file or folder (a whole name of it)"""
        return any(part in self._excluded for part in path.split("/"))

    def configure(self, db, verify: Callable[[str, str], Optional[int]]) -> None:
        """the db (the users and their contacts) and verify(user name, password): the user's id when they match, else
        None"""
        self._db = db
        self._verify = verify

    def mount(self, app) -> None:
        """serves the share on the (FastAPI) app, nothing when the hub doesn't serve it itself"""

    def start(self) -> None:
        """starts what keeps the share up to date, nothing when there is none"""

    def stop(self) -> None:
        pass

    def remember(self, user: dict, password: str) -> None:
        """the user (the db's: id, username, password hash) logged in or set this password: a share with its own
        password store takes it. nothing for one that asks the hub (verify)"""

    # ---------------------------------------------------------------- connecting
    def connect(self, user: dict, contacts: list[dict], host: str) -> dict:
        """what the app's network settings show to mount the folders: {"title", "notes": [what the user must do first],
        "contacts": [{"name", "address"}] (the shared ones, by name)}. user: the db's (get_user: id, username),
        contacts: theirs (get_contacts: id, name). host: the hub's address the way the app reaches it (the request's
        Host, name[:port])"""
        contacts = sorted(((contact.get("name"), int(contact["id"])) for contact in self._shared(user, contacts)),
                          key=lambda contact: self.folder_name(*contact).lower())
        return {"title": self.TITLE, "notes": self._notes(user),
                "contacts": [{"name": name, "address": self._address(host, name, contact_id)} for name, contact_id in contacts]}

    def _shared(self, user: dict, contacts: list[dict]) -> list[dict]:
        """the contacts whose folder is there: all"""
        return contacts

    def _notes(self, user: dict) -> list[str]:
        """what the user must do before the share works: nothing"""
        return []

    def _address(self, host: str, name: str, contact_id: int) -> str:
        """the URL of the contact's folder on host"""
        raise NotImplementedError

    @staticmethod
    def host_name(host: str) -> str:
        """the name of host (name[:port]) without the port, an IPv6 address in brackets"""
        name = urlsplit(f"//{host}").hostname or "localhost"
        return f"[{name}]" if ":" in name else name

    # ---------------------------------------------------------------- contacts
    @staticmethod
    def folder_name(name: str, contact_id: int) -> str:
        """the folder of a contact in the share: its name made safe for a file name, its id in brackets"""
        return f"{_UNSAFE.sub('_', name or '').strip() or 'contact'} ({int(contact_id)})"

    @staticmethod
    def folder_contact(folder: str) -> Optional[int]:
        """the contact id of a folder_name, None for another name"""
        match = _FOLDER_ID.search(folder or "")
        return int(match.group(1)) if match else None
