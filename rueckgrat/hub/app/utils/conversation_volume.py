"""the persistent files of a conversation: a docker named volume, mounted at MOUNT_PATH into its bash and run_code
sandboxes. a named volume and not a hub folder: the sandboxes are started through the host's docker.sock, a bind path
would be a host path. removed with the conversation, or by the maintenance (ConversationVolumeMaintenanceTask) after
STALE_DAYS without a message in the conversation. the user browses and downloads them through a short lived reader
container (ConversationVolume.entries, read_file, write_zip, files): the hub has no volume mounted"""
import io
import posixpath
import tarfile
import zipfile
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from typing import BinaryIO, Iterator

from app.common import get_logger
logger = get_logger()

MOUNT_PATH = "/sandbox/files"
SANDBOX_USER = "1000:1000"      # owns the files, the bash tool runs as it. run_code runs as root, the files are handed back after
STALE_DAYS = 7
LABEL = "rueckgrat.conversation_files"
# the image of the reader container: the python sandbox, in the image cache already (keep_template), it has find
READER_IMAGE = "ghcr.io/vndee/sandbox-python-311-bullseye"
READER_TIMEOUT = 30     # seconds for listing a folder
CHUNK = 64 * 1024
# left out of a zip on request: version control, caches and installed packages, not the user's work
EXCLUDED = frozenset({".git", ".cache", ".local", ".npm", "__pycache__", "node_modules", ".venv", "venv"})
# the type bits of go's os.FileMode in get_archive's stat: dir, symlink, device, named pipe, socket, char device, irregular
# the open sandboxes of a sharing() block: {"stack": ExitStack, "sessions": {key: (its ExitStack, session)}}
_SHARED: ContextVar[dict | None] = ContextVar("rueckgrat_shared_sessions", default=None)
_NOT_A_FILE = (1 << 31) | (1 << 27) | (1 << 26) | (1 << 25) | (1 << 24) | (1 << 21) | (1 << 19)


def _client():
    import docker   # only needed here, the hub runs without docker access too
    return docker.from_env()


class ConversationVolume:
    def __init__(self, user_id: int, conversation_id: int):
        self.user_id = int(user_id)
        self.conversation_id = int(conversation_id)

    @property
    def name(self) -> str:
        return f"rueckgrat-files-{self.conversation_id}"

    @staticmethod
    def clean_path(path: str) -> str:
        """a path under MOUNT_PATH as the user gives it, relative and normalized ("" is the root).
        ValueError when it leaves the files (.., absolute)"""
        path = (path or "").replace("\\", "/").strip()
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"invalid path {path!r}")
        path = posixpath.normpath(path) if path else ""
        return "" if path == "." else path

    def exists(self) -> bool:
        from docker.errors import NotFound
        try:
            _client().volumes.get(self.name)
            return True
        except NotFound:
            return False

    @classmethod
    def all(cls, user_id: int | None = None) -> list["ConversationVolume"]:
        """the volumes there are, of one user (None = all users)"""
        filters = {"label": [LABEL] + ([f"user_id={int(user_id)}"] if user_id is not None else [])}
        return [cls(volume.attrs["Labels"]["user_id"], volume.attrs["Labels"]["conversation_id"])
                for volume in _client().volumes.list(filters=filters)]

    def _mount(self, read_only: bool = False):
        """the mount of the volume, created with its labels on first use. read only: never created, check exists() first"""
        from docker.types import Mount
        if not read_only and not self.exists():
            _client().volumes.create(self.name, labels={LABEL: "1", "user_id": str(self.user_id),
                                                        "conversation_id": str(self.conversation_id)})
        return Mount(target=MOUNT_PATH, source=self.name, type="volume", read_only=read_only)

    @contextmanager
    def _reader(self, command: list[str] | None = None):
        """a created (not started) container with the volume read only at MOUNT_PATH, no network, removed when the
        block ends. get_archive reads from it as it is, a command (find) needs start()"""
        container = _client().containers.create(READER_IMAGE, command, mounts=[self._mount(read_only=True)],
                                                user=SANDBOX_USER, network_disabled=True, mem_limit="128m",
                                                labels={LABEL: "reader"})
        try:
            yield container
        finally:
            container.remove(force=True)

    def entries(self, path: str = "") -> list[dict]:
        """the folder's files and folders [{"name", "path", "type" file|dir|link, "size", "modified" epoch}], folders
        first. no volume (nothing written yet) is an empty folder, FileNotFoundError when the folder isn't there"""
        path = self.clean_path(path)
        if not self.exists():
            if path:
                raise FileNotFoundError(path)
            return []
        folder = posixpath.join(MOUNT_PATH, path) if path else MOUNT_PATH
        # \0 ends a line: a name may hold tabs and newlines. -P (the default): links are listed, never followed
        command = ["find", folder, "-mindepth", "1", "-maxdepth", "1", "-printf", "%y\\t%s\\t%T@\\t%f\\0"]
        with self._reader(command) as container:
            container.start()
            status = container.wait(timeout=READER_TIMEOUT)
            output = container.logs(stdout=True, stderr=False)
        if status.get("StatusCode"):
            raise FileNotFoundError(path)
        kinds = {"d": "dir", "f": "file", "l": "link"}
        entries = []
        for line in output.decode("utf-8", errors="replace").split("\0"):
            if line.count("\t") < 3:
                continue
            kind, size, modified, name = line.split("\t", 3)
            entries.append({"name": name, "path": posixpath.join(path, name) if path else name,
                            "type": kinds.get(kind, "other"), "size": int(size) if kind != "d" else 0,
                            "modified": int(float(modified))})
        return sorted(entries, key=lambda entry: (entry["type"] != "dir", entry["name"].lower()))

    def has_project(self) -> bool:
        """whether the files hold the user's work: a file or folder at the top that is not hidden or EXCLUDED (the bash
        tool keeps its shell state in .cache). False without a volume"""
        return any(not entry["name"].startswith(".") and entry["name"] not in EXCLUDED for entry in self.entries())

    def read_file(self, path: str) -> tuple[str, int, Iterator[bytes]]:
        """(name, size, chunks) of one regular file, the reader container stays until the chunks are read (or closed).
        FileNotFoundError for anything else: no volume, a folder, a link"""
        from docker.errors import NotFound
        path = self.clean_path(path)
        if not path or not self.exists():
            raise FileNotFoundError(path)
        stack = ExitStack()
        try:
            container = stack.enter_context(self._reader())
            stream, stat = container.get_archive(posixpath.join(MOUNT_PATH, path), chunk_size=CHUNK)
            if stat["mode"] & _NOT_A_FILE:
                raise FileNotFoundError(path)
        except NotFound:
            stack.close()
            raise FileNotFoundError(path)
        except BaseException:
            stack.close()
            raise

        def chunks():
            with stack, tarfile.open(fileobj=_ChunkReader(stream), mode="r|") as archive:
                member = archive.next()
                source = archive.extractfile(member) if member and member.isfile() else None
                while source and (data := source.read(CHUNK)):
                    yield data
        return posixpath.basename(path), int(stat["size"]), chunks()

    def _walk(self, path: str, exclude: bool) -> Iterator[tuple[list[str], tarfile.TarInfo, tarfile.TarFile]]:
        """(parts below path, member, its tar) of the folders and regular files at path (a clean_path), read from a
        reader container. exclude: no EXCLUDED names below path. links and special files are left out. no volume is
        an empty root, FileNotFoundError when path isn't there"""
        from docker.errors import NotFound
        if not self.exists():
            if path:
                raise FileNotFoundError(path)
            return
        with self._reader() as container:
            try:
                stream, _ = container.get_archive(posixpath.join(MOUNT_PATH, path) if path else MOUNT_PATH,
                                                  chunk_size=CHUNK)
            except NotFound:
                raise FileNotFoundError(path)
            with tarfile.open(fileobj=_ChunkReader(stream), mode="r|") as tar:
                for member in tar:
                    # the archive's first part is the name of path itself
                    parts = [part for part in member.name.split("/")[1:] if part not in ("", ".")]
                    if ".." in parts or (exclude and EXCLUDED.intersection(parts)):
                        continue
                    if member.isdir() or member.isfile():
                        yield parts, member, tar

    def write_zip(self, target: BinaryIO, path: str = "", exclude: bool = True) -> str:
        """the folder (or file) as a zip into target, everything under one folder named like it. exclude: no EXCLUDED
        names (.git, caches, installed packages) anywhere below it. links and special files are left out. no volume
        is an empty zip. returns the zip's file name. FileNotFoundError when path isn't there"""
        path = self.clean_path(path)
        top = posixpath.basename(path) or f"conversation_{self.conversation_id}_files"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for parts, member, tar in self._walk(path, exclude):
                name = "/".join([top, *parts])
                if member.isdir():
                    archive.writestr(_zip_info(name + "/", member), b"")
                    continue
                with archive.open(_zip_info(name, member), "w") as out:
                    source = tar.extractfile(member)
                    while data := source.read(CHUNK):
                        out.write(data)
        return f"{top}.zip"

    def files(self, path: str = "", exclude: bool = True, max_bytes: int | None = None) -> Iterator[tuple[str, int, bytes | None]]:
        """(path below MOUNT_PATH, size, bytes) of the file at path, or of every file below the folder path. bytes is
        None for a file larger than max_bytes. exclude, links, no volume, FileNotFoundError: like write_zip"""
        path = self.clean_path(path)
        for parts, member, tar in self._walk(path, exclude):
            if member.isfile():
                data = tar.extractfile(member).read() if max_bytes is None or member.size <= max_bytes else None
                yield "/".join([part for part in (path, *parts) if part]), member.size, data

    def _own(self, container) -> None:
        """hands every file to SANDBOX_USER: a new volume belongs to root, and so do the files a root run_code wrote"""
        container.exec_run(f"chown -R {SANDBOX_USER} {MOUNT_PATH}", user="root")

    @classmethod
    @contextmanager
    def sharing(cls):
        """within the block session() hands out one sandbox per volume and settings, started on first use and removed
        when the block ends: the calls of one round pay the container start once. nested blocks share the outer one"""
        if _SHARED.get() is not None:
            yield
            return
        with ExitStack() as stack:
            token = _SHARED.set({"stack": stack, "sessions": {}})
            try:
                yield
            finally:
                _SHARED.reset(token)

    @contextmanager
    def session(self, runtime_configs: dict, **kwargs):
        """a llm sandbox container with the volume at MOUNT_PATH: a fresh one removed when the block ends, inside a
        sharing() block the block's one for these settings. a call that fails drops a shared sandbox, the next call
        starts a fresh one. kwargs go to SandboxSession (lang, skip_environment_setup, ...)"""
        shared = _SHARED.get()
        if shared is None:
            with self._session(runtime_configs, **kwargs) as session:
                yield session
            return
        key = (self.name, repr(sorted(runtime_configs.items())), repr(sorted(kwargs.items())))
        if key not in shared["sessions"]:
            own = ExitStack()   # its own stack: a broken sandbox is removed alone
            shared["sessions"][key] = (own, own.enter_context(self._session(runtime_configs, **kwargs)))
            shared["stack"].callback(own.close)
        own, session = shared["sessions"][key]
        try:
            yield session
        except BaseException:
            shared["sessions"].pop(key, None)
            own.close()
            raise

    @contextmanager
    def _session(self, runtime_configs: dict, **kwargs):
        """a fresh llm sandbox container with the volume at MOUNT_PATH, removed when the block ends.
        keep_template: the language image stays, no pull per run"""
        from llm_sandbox import SandboxSession
        configs = {**runtime_configs, "mounts": [*runtime_configs.get("mounts", []), self._mount()]}
        with SandboxSession(keep_template=True, runtime_configs=configs, encoding_errors="replace", **kwargs) as session:
            self._own(session.container)
            try:
                yield session
            finally:
                self._own(session.container)

    def remove(self) -> None:
        """the volume and its files. a volume that isn't there, or no docker, is nothing to remove"""
        try:
            from docker.errors import NotFound
            try:
                _client().volumes.get(self.name).remove(force=True)
                logger.info(f"files of conversation {self.conversation_id} removed")
            except NotFound:
                pass
        except Exception as e:
            logger.error(f"files of conversation {self.conversation_id} not removed {repr(e)}")


def _zip_info(name: str, member: tarfile.TarInfo) -> zipfile.ZipInfo:
    """a zip entry with the tar member's time and permissions (zip times start in 1980)"""
    import time
    info = zipfile.ZipInfo(name, time.localtime(max(member.mtime, 315532800))[:6])
    info.external_attr = (member.mode & 0xFFFF | (0o040000 if member.isdir() else 0o100000)) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


class _ChunkReader(io.RawIOBase):
    """the chunks docker's get_archive yields as a file to read, for tarfile's stream mode"""
    def __init__(self, chunks: Iterator[bytes]):
        self._chunks = iter(chunks)
        self._rest = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        while not self._rest:
            self._rest = next(self._chunks, None)
            if self._rest is None:
                self._rest = b""
                return 0
        n = min(len(buffer), len(self._rest))
        buffer[:n], self._rest = self._rest[:n], self._rest[n:]
        return n
