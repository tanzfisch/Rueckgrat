"""#225 the contacts' sandbox files (SandboxVolume) as SMB shares (a FileShare): with HUB_FILE_SHARE=smb the smb service
(rueckgrat/smb, samba, the compose profile smb) serves them, the hub keeps its users and shares in the folder they share
(STATE_DIR here, /state there, the volume hub_smb):

  passwd        the share users, rg<user id> with the uid UID_BASE + user id (libnss-extrausers reads it there)
  smbpasswd     their NT hashes (samba's smbpasswd passdb)
  users.map     the hub user name each logs in with (samba's username map)
  shares.conf   one share per contact with files, "<name> (<id>)" (share_name), a copy of smb.conf's [contact]: only
                its user may use it (and sees it, access based share enum), the excluded names as veto files. the smb
                service reloads it when it changes

samba checks a login against the NT hash of the password (MD4), the hub keeps only its argon2 hash: the hub takes the NT
hash when the user gives the password (remember: signup, login, a password change; USERS_FILE). it is used while the hub
password stays the one it came with (a reset by the hub management drops it) and the password isn't empty. a user who
hasn't logged in since the share was turned on logs in once (the app) first.

the shares are the contacts' volumes in docker's volumes folder (HUB_SMB_VOLUMES on the host, VOLUMES there), samba
works in them as the sandbox user (force user, SANDBOX_UID): what the user makes belongs to the AI's sandbox user like
its own files. a volume is there once the contact's sandbox or files were used: refresh (every REFRESH_SECONDS, and
right after a login) shares the new ones, drops the gone contacts and users and renames.

the smb service is on port PORT_ENV of the hub's machine (HUB_SMB_PORT, 445 unless taken): connect tells it"""
import hashlib
import json
import os
import re
import struct
import threading
import time
from typing import Callable, Optional
from urllib.parse import quote

from app.common import get_logger
from app.utils.file_share import FileShare
from app.utils.sandbox_volume import SandboxVolume, SANDBOX_UID
logger = get_logger()

STATE_DIR = "/hub/smb"          # the volume hub_smb, the smb service's /state
VOLUMES = "/volumes"            # docker's volumes folder in the smb service (HUB_SMB_VOLUMES)
USERS_FILE = "users.json"       # the hub's own: {user id: {"name", "nt", "hub", "set"}}, the NT hashes it took
PASSWD = "passwd"
SMBPASSWD = "smbpasswd"
USERS_MAP = "users.map"
SHARES = "shares.conf"          # written last: the smb service reloads when it changes
UID_BASE = 20000                # the share user of hub user n is uid UID_BASE + n, its group the sandbox user's
UNIX_NAME = "rg{}"
SHARE_NAME_MAX = 80             # characters of an SMB share name
REFRESH_SECONDS = 15
PORT_ENV = "HUB_SMB_PORT"       # the smb service's port on the hub's machine
PORT = 445                      # SMB's own, unset or not a number: this one
# a hub user name samba's files can't hold (or the share user's name could clash), they get no share
_BAD_LOGIN = re.compile(r'["=:#;\\\x00-\x1f\x7f]|^\s|\s$')
# not in a share name ([] end a section, % starts a substitution, the rest SMB refuses), on top of folder_name's
_SHARE_UNSAFE = re.compile(r"[\[\]+=;,%]")
# veto files: names made of these only (a / ends a name, * and ? are patterns, % a substitution)
_VETO_SAFE = re.compile(r"^[A-Za-z0-9._~+ -]+$")


class SandboxSmb(FileShare):
    TITLE = "SMB"

    def __init__(self, volumes: Callable[[], list[SandboxVolume]] = SandboxVolume.all, state_dir: str = STATE_DIR):
        """volumes(): the contacts' volumes there are (all users)"""
        super().__init__()
        self._volumes = volumes
        self._state_dir = state_dir
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._warned: set[str] = set()     # the user names without a login, told once

    # ---------------------------------------------------------------- the refresher
    def start(self) -> None:
        """refresh now and then every REFRESH_SECONDS (sooner after a login), in the background"""
        if self._thread is None:
            self._stopped.clear()
            self._thread = threading.Thread(target=self._run, name="smb-shares", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stopped.is_set():
            self._wake.clear()
            try:
                self.refresh()
            except Exception as e:
                logger.error(f"smb shares not updated {repr(e)}")
            self._wake.wait(REFRESH_SECONDS)

    # ---------------------------------------------------------------- users
    def remember(self, user: dict, password: str) -> None:
        """takes the NT hash of the user's password (an empty one: no share login), refresh soon"""
        user_id = str(int(user["id"]))
        with self._lock:
            users = self._read_users()
            if password:
                nt = self.nt_hash(password)
                kept = users.get(user_id, {})
                if (kept.get("nt"), kept.get("name"), kept.get("hub")) != (nt, user["username"], self._hub(user)):
                    users[user_id] = {"name": user["username"], "nt": nt, "hub": self._hub(user), "set": int(time.time())}
                    self._write(USERS_FILE, json.dumps(users, indent=1, sort_keys=True))
            elif users.pop(user_id, None) is not None:
                self._write(USERS_FILE, json.dumps(users, indent=1, sort_keys=True))
        self._wake.set()

    @staticmethod
    def nt_hash(password: str) -> str:
        """samba's NT hash of the password: MD4 of its UTF-16LE, hex (hashlib's md4 is gone with OpenSSL 3)"""
        return _md4(password.encode("utf-16-le")).hex().upper()

    @staticmethod
    def _hub(user: dict) -> str:
        """a short fingerprint of the user's hub password hash: an NT hash is used while it is the same"""
        return hashlib.sha256((user.get("password") or "").encode()).hexdigest()[:16]

    @staticmethod
    def unix_name(user_id: int) -> str:
        return UNIX_NAME.format(int(user_id))

    def _logins(self, users: dict) -> tuple[dict[int, dict], list[str]]:
        """({user id: kept entry} of the kept users that log in with them, [the stale ones' ids]): a login is still
        there with the same name and hub password (else stale), a name samba can hold, unique without case (the first
        user keeps it)"""
        logins, stale, names = {}, [], set()
        for user_id in sorted(users, key=int):
            entry = users[user_id]
            user = self._db.get_user_by_id(int(user_id))
            if not user or user["username"] != entry["name"] or self._hub(user) != entry["hub"]:
                stale.append(user_id)
                continue
            if _BAD_LOGIN.search(entry["name"]) or entry["name"].lower() in names:
                if entry["name"] not in self._warned:
                    self._warned.add(entry["name"])
                    logger.warning(f"user {user_id}: no smb login, the name {entry['name']!r} can't be one")
                continue
            names.add(entry["name"].lower())
            logins[int(user_id)] = entry
        return logins, stale

    # ---------------------------------------------------------------- connecting
    @staticmethod
    def port() -> int:
        """HUB_SMB_PORT, PORT when unset or not a port"""
        port = os.environ.get(PORT_ENV, "").strip()
        return int(port) if port.isdigit() and 0 < int(port) < 65536 else PORT

    def _shared(self, user: dict, contacts: list[dict]) -> list[dict]:
        """the contacts with a volume (a share once the user has a login)"""
        shared = {volume.contact_id for volume in self._volumes() if volume.user_id == int(user["id"])}
        return [contact for contact in contacts if int(contact["id"]) in shared]

    def _notes(self, user: dict) -> list[str]:
        """a user without a login yet logs in once"""
        with self._lock:
            logins, _ = self._logins(self._read_users())
        return [] if int(user["id"]) in logins else ["No SMB login yet: log out and in again in the app once."]

    def _address(self, host: str, name: str, contact_id: int) -> str:
        """the share's smb:// URL on host (the app's address of the hub), the port unless 445"""
        port = self.port()
        return f"smb://{self.host_name(host)}{'' if port == PORT else f':{port}'}/{quote(self.share_name(name, contact_id))}"

    # ---------------------------------------------------------------- shares
    @classmethod
    def share_name(cls, name: str, contact_id: int) -> str:
        """the contact's share: its folder_name made safe for SMB, at most SHARE_NAME_MAX characters"""
        tail = f" ({int(contact_id)})"
        base = _SHARE_UNSAFE.sub("_", cls.folder_name(name, contact_id)[:-len(tail)])
        return (base[:SHARE_NAME_MAX - len(tail)].strip() or "contact") + tail

    def _shares(self, logins: dict[int, dict]) -> list[tuple[str, str, int]]:
        """(share name, path in the smb service, user id) of the volumes of the logins' contacts, by name"""
        names = {}
        for user_id in logins:
            names.update({(user_id, int(contact["id"])): contact.get("name") for contact in self._db.get_contacts(user_id)})
        shares = [(self.share_name(names[(volume.user_id, volume.contact_id)], volume.contact_id),
                   f"{VOLUMES}/{volume.name}/_data", volume.user_id)
                  for volume in self._volumes() if (volume.user_id, volume.contact_id) in names]
        return sorted(shares, key=lambda share: share[0].lower())

    # ---------------------------------------------------------------- the files
    def refresh(self) -> None:
        """writes the smb service's files from the hub's users, their contacts and volumes. a file is only written
        when it changes, shares.conf last"""
        with self._lock:
            users = self._read_users()
            logins, stale = self._logins(users)
            if stale:       # gone users, changed passwords: their NT hashes go
                self._write(USERS_FILE, json.dumps({user_id: entry for user_id, entry in users.items() if user_id not in stale},
                                                   indent=1, sort_keys=True))
            self._write(PASSWD, self._passwd(logins), mode=0o644)
            self._write(SMBPASSWD, self._smbpasswd(logins))
            self._write(USERS_MAP, self._users_map(logins), mode=0o644)
            self._write(SHARES, self._shares_conf(self._shares(logins)), mode=0o644)

    def _passwd(self, logins: dict[int, dict]) -> str:
        return "".join(f"{self.unix_name(user_id)}:x:{UID_BASE + user_id}:{SANDBOX_UID}::/nonexistent:/usr/sbin/nologin\n"
                       for user_id in sorted(logins))

    def _smbpasswd(self, logins: dict[int, dict]) -> str:
        # name:uid:LM hash (none):NT hash:[flags]:LCT-<last change, hex>:
        return "".join(f"{self.unix_name(user_id)}:{UID_BASE + user_id}:{'X' * 32}:{entry['nt']}:[U          ]:"
                       f"LCT-{int(entry.get('set', 0)):08X}:\n" for user_id, entry in sorted(logins.items()))

    def _users_map(self, logins: dict[int, dict]) -> str:
        return "".join(f'{self.unix_name(user_id)} = "{entry["name"]}"\n' for user_id, entry in sorted(logins.items()))

    def _shares_conf(self, shares: list[tuple[str, str, int]]) -> str:
        """included at the end of the smb service's smb.conf: the shares, each a copy of its [contact] with the path, the
        one user and the excluded names (veto files)"""
        lines = ["# written by the hub (SandboxSmb), each change replaces it"]
        veto = sorted(name for name in self._excluded if _VETO_SAFE.match(name))
        for name, path, user_id in shares:
            lines += ["", f"[{name}]", "copy = contact", "available = yes", "browseable = yes", f"path = {path}",
                      f"valid users = {self.unix_name(user_id)}"] + ([f"veto files = /{'/'.join(veto)}/"] if veto else [])
        return "\n".join(lines) + "\n"

    def _read_users(self) -> dict:
        try:
            with open(os.path.join(self._state_dir, USERS_FILE)) as file:
                return json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.error(f"smb users not read, none kept {repr(e)}")
            return {}

    def _write(self, name: str, content: str, mode: int = 0o600) -> None:
        """replaces the state file name with content (atomically), unless it holds that already"""
        path = os.path.join(self._state_dir, name)
        try:
            with open(path) as file:
                if file.read() == content:
                    return
        except FileNotFoundError:
            pass
        part = f"{path}.part"
        with open(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as file:
            file.write(content)
        os.chmod(part, mode)
        os.replace(part, path)


def _md4(data: bytes) -> bytes:
    """MD4 (RFC 1320)"""
    def rotate(x, n):
        x &= 0xFFFFFFFF
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    message = data + b"\x80" + b"\x00" * ((55 - len(data)) % 64) + struct.pack("<Q", len(data) * 8)
    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476]
    for chunk in range(0, len(message), 64):
        x = struct.unpack("<16I", message[chunk:chunk + 64])
        a, b, c, d = h
        for i in range(16):
            k, s = i, (3, 7, 11, 19)[i % 4]
            a, b, c, d = d, rotate(a + ((b & c) | (~b & d)) + x[k], s), b, c
        for i in range(16):
            k, s = (i % 4) * 4 + i // 4, (3, 5, 9, 13)[i % 4]
            a, b, c, d = d, rotate(a + ((b & c) | (b & d) | (c & d)) + x[k] + 0x5A827999, s), b, c
        for i in range(16):
            k, s = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)[i], (3, 9, 11, 15)[i % 4]
            a, b, c, d = d, rotate(a + (b ^ c ^ d) + x[k] + 0x6ED9EBA1, s), b, c
        h = [(value + new) & 0xFFFFFFFF for value, new in zip(h, (a, b, c, d))]
    return struct.pack("<4I", *h)
