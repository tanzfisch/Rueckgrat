"""#193 the contacts' sandbox files (SandboxVolume) as a WebDAV share: the user mounts them as a network drive. off unless
HUB_WEBDAV is on, then the hub serves it at MOUNT (/dav) with wsgidav (main.py: SandboxDav.mount).

  /dav/                     the user's contacts, one folder "<name> (<id>)" each
  /dav/<name> (<id>)/...    the contact's files, as the AI sees them under /home

the hub's user name and password log in (HTTP Basic, the hub is behind caddy's https). each request works through the
reader containers of SandboxVolume (the hub has no volume mounted), a folder's listing is kept LISTING_SECONDS.

while the user holds a WebDAV lock anywhere in a contact's files (an editor that locks the file it has open), or paused
the AI's writes (pause), the AI does not write them: SandboxVolume.write_block asks write_block here, its file writes are
refused and its sandboxes see the files read only. the locks are wsgidav's own (its LockStorageDict, in memory: a hub
restart drops them like the pauses)"""
import io
import logging
import os
import posixpath
import re
import tempfile
import threading
import time
from typing import Callable, Optional
from urllib.parse import quote, unquote

from wsgidav import util
from wsgidav.dav_error import DAVError, HTTP_FORBIDDEN
from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider
from wsgidav.dc.base_dc import BaseDomainController
from wsgidav.lock_man.lock_storage import LockStorageDict

from app.common import get_logger
from app.utils.sandbox_volume import SandboxVolume, SPOOL_BYTES
logger = get_logger()

MOUNT = "/dav"
ENABLED_ENV = "HUB_WEBDAV"
REALM = "Rueckgrat"
LISTING_SECONDS = 2.0       # a folder's listing is used again this long: a client asks for the same folder many times
LISTING_CACHE = 256         # listings kept at most
USER_ID = "rueckgrat.user_id"   # the logged in user's id in the request's environ (_Users)
PAUSED_REASON = "the user paused your writes to the files, they are read only until the user resumes them"
LOCKED_REASON = "the user has files open over the network drive (a WebDAV lock), they are read only until the user closes them"
_FOLDER_ID = re.compile(r"\((\d+)\)$")
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


class SandboxDav:
    def __init__(self, volumes: Callable[[int, int], SandboxVolume] = SandboxVolume):
        """volumes(user id, contact id): the files of a contact"""
        self._volumes = volumes
        self._db = None
        self._verify: Optional[Callable[[str, str], Optional[int]]] = None
        self._locks = _Locks()
        self._paused: set[tuple[int, int]] = set()
        self._listings: dict[tuple[str, str], tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()
        self._wsgi = None

    @staticmethod
    def enabled() -> bool:
        """HUB_WEBDAV is on (true, 1, yes, on)"""
        return os.environ.get(ENABLED_ENV, "").strip().lower() in ("1", "true", "yes", "on")

    def configure(self, db, verify: Callable[[str, str], Optional[int]]) -> None:
        """the db (the users' contacts) and verify(user name, password): the user's id when they match, else None"""
        self._db = db
        self._verify = verify

    def wsgi(self):
        """the wsgidav app of the share, made once"""
        with self._lock:
            if self._wsgi is None:
                from wsgidav.wsgidav_app import WsgiDAVApp
                self._wsgi = WsgiDAVApp({
                    "provider_mapping": {"/": _Provider(self)},
                    "mount_path": MOUNT,
                    "lock_storage": self._locks,
                    "property_manager": True,       # dead properties (the clients' own), in memory
                    "http_authenticator": {"domain_controller": _Users, "accept_basic": True, "accept_digest": False,
                                           "default_to_digest": False},
                    "rueckgrat_dav": self,          # for _Users
                    # directory_slash off: its redirect of a folder without "/" leaves out MOUNT (and the clients
                    # don't follow redirects)
                    "dir_browser": {"enable": True, "response_trailer": False, "davmount": True,
                                    "directory_slash": False},
                    "suppress_version_info": True,
                    # its logger "wsgidav" at WARNING (verbose 2): failed logins and errors, not each request
                    "verbose": 2,
                    "logging": {"enable": True, "logger_format": "%(levelname)s:  wsgidav: %(message)s"},
                })
            return self._wsgi

    def mount(self, app) -> None:
        """serves the share on the (FastAPI) app: MOUNT/... and MOUNT itself like MOUNT/, any method. the app's own
        answer to MOUNT, a redirect to MOUNT/ (with http:// behind the proxy), fails clients like gvfs"""
        from a2wsgi import WSGIMiddleware
        share = WSGIMiddleware(self.wsgi())
        app.mount(MOUNT, share)
        app.add_route(MOUNT, _Root(share), include_in_schema=False)
        _QuietAccess.install()

    # ---------------------------------------------------------------- users and contacts
    def user(self, user_name: str, password: str) -> Optional[int]:
        """the id of the user these credentials log in, None when they don't (or the hub isn't configured yet)"""
        return self._verify(user_name, password) if self._verify is not None else None

    @staticmethod
    def folder_name(name: str, contact_id: int) -> str:
        """the folder of a contact in the share: its name made safe for a file name, its id in brackets"""
        return f"{_UNSAFE.sub('_', name or '').strip() or 'contact'} ({int(contact_id)})"

    @staticmethod
    def folder_contact(folder: str) -> Optional[int]:
        """the contact id of a folder_name, None for another name"""
        match = _FOLDER_ID.search(folder or "")
        return int(match.group(1)) if match else None

    def folders(self, user_id: int) -> list[str]:
        """the folder names of the user's contacts"""
        return [self.folder_name(contact.get("name"), contact["id"]) for contact in self._db.get_contacts(user_id)]

    def volume(self, user_id: int, folder: str) -> Optional[SandboxVolume]:
        """the files of the user's contact of folder, None for a folder that isn't one of theirs"""
        contact_id = self.folder_contact(folder)
        if contact_id is None or not self._db.owns_contact(user_id, contact_id):
            return None
        return self._volumes(user_id, contact_id)

    # ---------------------------------------------------------------- listings
    def listing(self, volume: SandboxVolume, folder: str) -> list[dict]:
        """the files and folders in folder (SandboxVolume.entries without links and special files), the same one for
        LISTING_SECONDS. FileNotFoundError when the folder isn't there"""
        key = (volume.name, folder)
        now = time.monotonic()
        with self._lock:
            kept = self._listings.get(key)
            if kept is not None and now - kept[0] < LISTING_SECONDS:
                return kept[1]
        entries = [entry for entry in volume.entries(folder) if entry["type"] in ("dir", "file")]
        with self._lock:
            self._listings[key] = (now, entries)
            if len(self._listings) > LISTING_CACHE:
                for old in sorted(self._listings, key=lambda k: self._listings[k][0])[:len(self._listings) - LISTING_CACHE]:
                    del self._listings[old]
        return entries

    def entry(self, volume: SandboxVolume, path: str) -> Optional[dict]:
        """the entry of path (its folder's listing), the root is a folder. None when nothing is there"""
        if not path:
            return volume.info("")
        folder, name = posixpath.split(path)
        try:
            return next((entry for entry in self.listing(volume, folder) if entry["name"] == name), None)
        except FileNotFoundError:
            return None

    def changed(self, volume: SandboxVolume) -> None:
        """the user changed the files: their listings are read again"""
        with self._lock:
            for key in [key for key in self._listings if key[0] == volume.name]:
                del self._listings[key]

    # ---------------------------------------------------------------- the AI's writes
    def pause(self, user_id: int, contact_id: int, paused: bool) -> None:
        """pauses (or resumes) the AI's writes to the contact's files"""
        with self._lock:
            (self._paused.add if paused else self._paused.discard)((int(user_id), int(contact_id)))

    def paused(self, user_id: int, contact_id: int) -> bool:
        with self._lock:
            return (int(user_id), int(contact_id)) in self._paused

    def locked(self, contact_id: int) -> bool:
        """whether a WebDAV lock is held anywhere in the contact's files (expired ones are not)"""
        locks = self._locks.get_lock_list("/", include_root=True, include_children=True, token_only=False)
        # a lock's root is the quoted path of what it locks (DAVResource.get_ref_url)
        return any(self.folder_contact(unquote(lock["root"]).strip("/").split("/")[0]) == int(contact_id) for lock in locks)

    def write_block(self, volume: SandboxVolume) -> Optional[str]:
        """why the AI may not write the files now (paused, locked), None when it may: SandboxVolume.set_write_check"""
        if self.paused(volume.user_id, volume.contact_id):
            return PAUSED_REASON
        if self.locked(volume.contact_id):
            return LOCKED_REASON
        return None


class _Root:
    """the asgi app of the route MOUNT (no "/"): the share's app with the request as one for MOUNT/, the way the app's
    mount at MOUNT hands it on (root_path MOUNT, path MOUNT/)"""

    def __init__(self, share):
        self._share = share

    async def __call__(self, scope, receive, send):
        root = scope.get("root_path", "") + MOUNT
        await self._share({**scope, "root_path": root, "path": scope["path"] + "/",
                           "raw_path": (scope.get("raw_path") or scope["path"].encode()) + b"/"}, receive, send)


class _QuietAccess(logging.Filter):
    """drops uvicorn's access log lines of the share's successful requests (MOUNT and below, status < 400): a client
    walks the folders over and over. its 4xx and 5xx (failed logins, errors) and all other requests stay. next to the
    hub's QuietPathFilter (app.common) on the same logger"""
    LOGGER = "uvicorn.access"

    @classmethod
    def install(cls) -> None:
        access = logging.getLogger(cls.LOGGER)
        if not any(isinstance(f, cls) for f in access.filters):
            access.addFilter(cls())

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access: args = (client, method, path with query, http version, status)
        args = record.args
        if not (isinstance(args, tuple) and len(args) >= 5):
            return True
        path = str(args[2]).split("?", 1)[0]
        if path != MOUNT and not path.startswith(MOUNT + "/"):
            return True
        try:
            return int(args[4]) >= 400
        except (TypeError, ValueError):
            return True


class _Locks(LockStorageDict):
    """wsgidav's in-memory locks, the expired ones purged (its optional cleanup) before a listing with children:
    LockStorageDict.get_lock_list purges an expired lock while it iterates its dict, a RuntimeError otherwise"""

    def cleanup(self):
        if self._dict is not None:
            for key in [key for key in list(self._dict) if not key.startswith("URL2TOKEN:")]:
                self.get(key)       # purges it when expired

    def get_lock_list(self, path, *, include_root, include_children, token_only):
        if include_children:
            self.cleanup()
        return super().get_lock_list(path, include_root=include_root, include_children=include_children,
                                     token_only=token_only)


class _Users(BaseDomainController):
    """HTTP Basic with the hub's users (SandboxDav.user), the user's id goes into the environ (USER_ID)"""

    def __init__(self, wsgidav_app, config):
        super().__init__(wsgidav_app, config)
        self._dav: SandboxDav = config["rueckgrat_dav"]

    def get_domain_realm(self, path_info, environ):
        return REALM

    def require_authentication(self, realm, environ):
        return True

    def basic_auth_user(self, realm, user_name, password, environ):
        user_id = self._dav.user(user_name, password)
        if user_id is None:
            return False
        environ[USER_ID] = user_id
        return True

    def supports_http_digest_auth(self):
        return False


class _Provider(DAVProvider):
    """the share's paths: the root lists the user's contacts, below a contact folder its files"""

    def __init__(self, dav: SandboxDav):
        super().__init__()
        self._dav = dav

    def dav(self) -> SandboxDav:
        return self._dav

    def split(self, path: str, environ: dict) -> tuple[Optional[SandboxVolume], str]:
        """(the files of the contact folder path is in, the path below it). (None, "") for the root and a folder that
        isn't the user's contact. ValueError for a path that leaves the files"""
        parts = [part for part in path.split("/") if part]
        user_id = environ.get(USER_ID)
        if not parts or user_id is None:
            return None, ""
        volume = self._dav.volume(user_id, parts[0])
        return volume, SandboxVolume.clean_path("/".join(parts[1:])) if volume is not None else ""

    def get_resource_inst(self, path: str, environ: dict):
        if environ.get(USER_ID) is None:
            return None
        if not path.strip("/"):
            return _Contacts(path, environ)
        try:
            volume, inner = self.split(path, environ)
        except ValueError:
            return None
        if volume is None:
            return None
        entry = self._dav.entry(volume, inner)
        if entry is None:
            return None
        return _resource(path, environ, volume, entry)


def _resource(path: str, environ: dict, volume: SandboxVolume, entry: dict):
    return (_Folder if entry["type"] == "dir" else _File)(path, environ, volume, entry)


class _Contacts(DAVCollection):
    """the share's root: a folder per contact of the user, nothing else is made here"""

    def get_member_names(self):
        return self.provider.dav().folders(self.environ[USER_ID])

    def get_display_name(self):
        return REALM

    def create_empty_resource(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def create_collection(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def delete(self):
        raise DAVError(HTTP_FORBIDDEN)

    def copy_move_single(self, dest_path, *, is_move):
        raise DAVError(HTTP_FORBIDDEN)

    def support_recursive_move(self, dest_path):
        return False

    def support_recursive_delete(self):
        return False


class _Item:
    """what files and folders share: their contact's files, their entry and the user's changes to them"""
    _volume: SandboxVolume
    _entry: dict

    def _bind(self, volume: SandboxVolume, entry: dict) -> None:
        self._volume = volume
        self._entry = entry

    def _inner(self) -> str:
        """the path below the contact folder"""
        return self._entry["path"]

    def _changed(self, path: str) -> None:
        """after a change at path (a share path): the listings are read again, path's locks and properties go (they are
        kept by its quoted path like DAVResource.get_ref_url)"""
        self.provider.dav().changed(self._volume)
        self.provider.lock_manager.remove_all_locks_from_url(quote(path), recursive=True)
        if self.provider.prop_manager:
            self.provider.prop_manager.remove_properties(quote(path), self.environ)

    def _target(self, dest_path: str) -> str:
        """the path below the contact folder of a copy or move target, in the same contact's files (else 403)"""
        volume, inner = self.provider.split(dest_path, self.environ)
        if volume is None or volume.name != self._volume.name or not inner:
            raise DAVError(HTTP_FORBIDDEN, "copy and move only within one contact's files")
        return inner

    def get_last_modified(self):
        return self._entry["modified"] or None

    def get_creation_date(self):
        return None

    def delete(self):
        if not self._inner():
            raise DAVError(HTTP_FORBIDDEN)
        self._volume.delete(self._inner())
        self._changed(self.path)

    def handle_move(self, dest_path):
        self._volume.move(self._inner(), self._target(dest_path))
        self._changed(self.path)
        self._changed(dest_path)
        return True

    def handle_copy(self, dest_path, *, depth_infinity):
        target = self._target(dest_path)
        if self.is_collection and not depth_infinity:
            self._volume.delete(target)
            self._volume.make_folder(target)
        else:
            self._volume.copy(self._inner(), target)
        self._changed(dest_path)
        return True

    def copy_move_single(self, dest_path, *, is_move):
        raise DAVError(HTTP_FORBIDDEN)      # handle_copy and handle_move do it natively

    def support_recursive_move(self, dest_path):
        return False


class _Folder(_Item, DAVCollection):
    def __init__(self, path: str, environ: dict, volume: SandboxVolume, entry: dict):
        DAVCollection.__init__(self, path, environ)
        self._bind(volume, entry)

    def get_member_list(self):
        return [_resource(util.join_uri(self.path, entry["name"]), self.environ, self._volume, entry)
                for entry in self.provider.dav().listing(self._volume, self._inner())]

    def get_member_names(self):
        return [entry["name"] for entry in self.provider.dav().listing(self._volume, self._inner())]

    def get_display_name(self):
        return self._entry["name"] or self.name

    def create_empty_resource(self, name):
        """an empty file. for a PUT it is written by the PUT (end_write), not twice"""
        inner = posixpath.join(self._inner(), name)
        if self.environ.get("REQUEST_METHOD") != "PUT":
            self._volume.upload(inner, io.BytesIO(b""), 0)
            self.provider.dav().changed(self._volume)
        return _File(util.join_uri(self.path, name), self.environ, self._volume,
                     {"name": name, "path": inner, "type": "file", "size": 0, "modified": int(time.time())})

    def create_collection(self, name):
        self._volume.make_folder(posixpath.join(self._inner(), name))
        self.provider.dav().changed(self._volume)

    def support_recursive_delete(self):
        return True


class _File(_Item, DAVNonCollection):
    def __init__(self, path: str, environ: dict, volume: SandboxVolume, entry: dict):
        DAVNonCollection.__init__(self, path, environ)
        self._bind(volume, entry)
        self._upload = None

    def get_content_length(self):
        return self._entry["size"]

    def get_content_type(self):
        return util.guess_mime_type(self.path)

    def get_display_name(self):
        return self._entry["name"]

    def get_etag(self):
        return f"{self._entry['size']}-{self._entry['modified']}"

    def support_etag(self):
        return True

    def support_ranges(self):
        return False

    def get_content(self):
        return self._volume.open_file(self._inner())

    def begin_write(self, *, content_type=None):
        """the PUT's bytes go into a spooled file, end_write uploads them"""
        self._upload = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)
        return _Kept(self._upload)

    def end_write(self, *, with_errors):
        upload, self._upload = self._upload, None
        with upload:
            if with_errors:
                return
            size = upload.tell()
            upload.seek(0)
            self._volume.upload(self._inner(), upload, size)
        self._entry = {**self._entry, "size": size, "modified": int(time.time())}     # the PUT's ETag
        self.provider.dav().changed(self._volume)


class _Kept(io.RawIOBase):
    """the spooled file of an upload for wsgidav to write into: its close (after the last chunk) leaves it open for
    end_write"""

    def __init__(self, target):
        self._target = target

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        return self._target.write(data)
