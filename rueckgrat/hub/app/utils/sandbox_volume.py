"""the persistent sandbox files of one contact: a docker named volume, mounted at MOUNT_PATH into the bash and run_code
sandboxes of all the contact's conversations, so projects outlive a conversation. a named volume and not a hub folder:
the sandboxes are started through the host's docker.sock, a bind path would be a host path. removed with the contact,
or by the maintenance (ConversationVolumeMaintenanceTask) when the contact is gone or after STALE_DAYS without a message
in any of its conversations. the user browses and downloads them through a short lived reader container
(SandboxVolume.entries, read_file, write_zip, files): the hub has no volume mounted. the user's own changes (the
WebDAV share, sandbox_dav) go through reader containers too (upload, make_folder, delete, move, copy).

the layout (LAYOUT, made at every sandbox start):
  projects/<name>/        one folder per project, its PROJECT.md says what it is, its status and how to run it
  workdir/<conversation>/ where bash and run_code of a conversation start, its scratch work
  data/documents/<hash>/  the files write_file writes, <hash> of the content: a write never overwrites another
  data/images/            generated images
  data/tts/               generated text to speach files
  .cache/rueckgrat/shell/<conversation>/  the bash terminal of a conversation (its folder, variables, functions)"""
import hashlib
import io
import posixpath
import re
import tarfile
import tempfile
import time
import zipfile
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from typing import BinaryIO, Iterable, Iterator, Optional

from app.common import get_logger
from app.utils.text_files import sanitize_relative_path
logger = get_logger()

MOUNT_PATH = "/home"
SANDBOX_USER = "1000:1000"      # owns the files, the bash tool runs as it. run_code runs as root, the files are handed back after
SANDBOX_UID = 1000
STALE_DAYS = 30
LABEL = "rueckgrat.contact_files"
PROJECTS = "projects"
PROJECT_FILE = "PROJECT.md"
WORKDIR = "workdir"
DOCUMENTS = "data/documents"
IMAGES = "data/images"
TTS = "data/tts"
LAYOUT = (PROJECTS, WORKDIR, DOCUMENTS, IMAGES, TTS)
SHELL_STATE = ".cache/rueckgrat/shell"
HASH_CHARS = 12         # of the sha256 of a document's (or audio file's) content, its folder in DOCUMENTS (TTS)
# the image of the bash sandbox and the reader containers (rueckgrat/sandbox/Dockerfile, built by compose): the python
# sandbox with C and C++ builds (cmake, ninja), it has find
SANDBOX_IMAGE = "rueckgrat-sandbox:latest"
MAX_PROJECT_NAME = 40   # characters of a project's folder name (project_name)
MAX_PROJECT_TRIES = 99  # a new project's folder: its name, then name_2 up to name_<this> (reserve_project)
READER_TIMEOUT = 30     # seconds for listing a folder
CHUNK = 64 * 1024
SPOOL_BYTES = 32 * 1024 * 1024     # an upload's tar is kept in memory up to this size, on disk beyond
# a find -printf line of entries and info, \0 ends it: a name may hold tabs and newlines
FIND_FORMAT = "%y\\t%s\\t%T@\\t%f\\0"
# left out of a zip on request: version control, caches and installed packages, not the user's work
EXCLUDED = frozenset({".git", ".cache", ".local", ".npm", "__pycache__", "node_modules", ".venv", "venv"})
# the open sandboxes of a sharing() block: {"stack": ExitStack, "sessions": {key: (its ExitStack, session)}}
_SHARED: ContextVar[dict | None] = ContextVar("rueckgrat_shared_sessions", default=None)
# the type bits of go's os.FileMode in get_archive's stat: dir, symlink, device, named pipe, socket, char device, irregular
_NOT_A_FILE = (1 << 31) | (1 << 27) | (1 << 26) | (1 << 25) | (1 << 24) | (1 << 21) | (1 << 19)


def _client():
    import docker   # only needed here, the hub runs without docker access too
    return docker.from_env()


class SandboxVolume:
    def __init__(self, user_id: int, contact_id: int):
        self.user_id = int(user_id)
        self.contact_id = int(contact_id)

    @classmethod
    def of_conversation(cls, db, user_id: int, conversation_id: int) -> "SandboxVolume":
        """the volume of the conversation's contact. ValueError when the conversation is gone"""
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"conversation {conversation_id} not found")
        return cls(user_id, conversation["contact_id"])

    @property
    def name(self) -> str:
        return f"rueckgrat-files-contact-{self.contact_id}"

    @staticmethod
    def clean_path(path: str) -> str:
        """a path under MOUNT_PATH as the user gives it, relative and normalized ("" is the root).
        ValueError when it leaves the files (.., absolute)"""
        path = (path or "").replace("\\", "/").strip()
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"invalid path {path!r}")
        path = posixpath.normpath(path) if path else ""
        return "" if path == "." else path

    @staticmethod
    def workdir(conversation_id: int) -> str:
        """the folder a conversation's bash and run_code start in, absolute"""
        return f"{MOUNT_PATH}/{WORKDIR}/{int(conversation_id)}"

    @staticmethod
    def shell_state(conversation_id: int) -> str:
        """the folder of the conversation's bash terminal state (BashTool), absolute"""
        return f"{MOUNT_PATH}/{SHELL_STATE}/{int(conversation_id)}"

    @staticmethod
    def document_path(name: str, data: bytes) -> str:
        """where write_file keeps the file name (a relative path) with these bytes: DOCUMENTS/<hash>/<name>"""
        return SandboxVolume._hashed_path(DOCUMENTS, name, data)

    @staticmethod
    def tts_path(name: str, data: bytes) -> str:
        """where text_to_speech keeps the audio file name with these bytes: TTS/<hash>/<name>"""
        return SandboxVolume._hashed_path(TTS, name, data)

    @staticmethod
    def _hashed_path(folder: str, name: str, data: bytes) -> str:
        """folder/<hash of the content>/name: a file kept this way never overwrites another"""
        return f"{folder}/{hashlib.sha256(data).hexdigest()[:HASH_CHARS]}/{name}"

    def current_dir(self, conversation_id: int) -> str:
        """the folder the conversation's bash ended in (its shell state), relative to MOUNT_PATH, its workdir when it
        has none yet or it is outside the files"""
        default = self.clean_path(self.workdir(conversation_id).removeprefix(MOUNT_PATH + "/"))
        try:
            _, _, chunks = self.read_file(f"{self.shell_state(conversation_id)}/cwd".removeprefix(MOUNT_PATH + "/"))
            cwd = b"".join(chunks).decode("utf-8", errors="replace").strip()
        except FileNotFoundError:
            return default
        if cwd == MOUNT_PATH:
            return ""
        try:
            return self.clean_path(cwd.removeprefix(MOUNT_PATH + "/")) if cwd.startswith(MOUNT_PATH + "/") else default
        except ValueError:
            return default

    @staticmethod
    def full_path(path: str) -> Optional[str]:
        """a path the AI gives in full, under MOUNT_PATH (/home/...) or ~ (~/...), as a clean_path ("" the root). None for
        a relative one. ValueError when it is outside the files"""
        path = (path or "").replace("\\", "/").strip()
        if path == MOUNT_PATH or path.startswith(MOUNT_PATH + "/"):
            joined = path.removeprefix(MOUNT_PATH).lstrip("/")
        elif path.startswith("/") or path.startswith("~"):
            if not (path == "~" or path.startswith("~/")):
                raise ValueError(f"{path} is outside your files")
            joined = path[1:].lstrip("/")
        else:
            return None
        return SandboxVolume._inside(path, joined)

    @staticmethod
    def _inside(path: str, joined: str) -> str:
        """joined (path relative to MOUNT_PATH) normalized as a clean_path, ValueError when it leaves the files"""
        joined = posixpath.normpath(joined) if joined else ""
        if joined.startswith("..") or joined.startswith("/"):
            raise ValueError(f"{path} is outside your files")
        return SandboxVolume.clean_path("" if joined == "." else joined)

    @staticmethod
    def file_path(path: str) -> Optional[str]:
        """where a tool writes a file the AI names by its full path (full_path), None for a plain name (the tool keeps it
        in its own folder, document_path, tts_path). ValueError when it is outside the files, the root, hidden (.cache) or
        not a valid file name (sanitize_relative_path)"""
        full = SandboxVolume.full_path(path)
        if full is None:
            return None
        if not full or sanitize_relative_path(full) != full:
            raise ValueError(f"{path} is not a valid path for a file (no hidden files or folders, at most 8 folders deep)")
        return full

    def resolve(self, path: str, conversation_id: int) -> str:
        """a path as the AI gives it, absolute under MOUNT_PATH (full_path) or relative to the conversation's current
        folder (current_dir), as a clean_path. ValueError when it is outside the files"""
        full = self.full_path(path)
        if full is not None:
            return full
        path = (path or "").replace("\\", "/").strip()
        return self._inside(path, posixpath.join(self.current_dir(conversation_id), path))

    def read_paths(self, paths: list[str], conversation_id: int, max_bytes: int) -> Iterator[tuple[str, bytes]]:
        """(path below MOUNT_PATH, bytes) of the files of paths as the AI gives them (resolve), one after another in
        their order, a folder's files by name: what text_to_speech speaks and join_files joins. ValueError naming the
        path that is outside the files, not there, an empty folder or a file larger than max_bytes"""
        for path in paths:
            try:
                real = self.resolve(path, conversation_id)
                files = sorted(self.files(real, max_bytes=max_bytes))
            except FileNotFoundError:
                raise ValueError(f"{path} is not in your files")
            except ValueError:
                raise ValueError(f"{path} is not a path in your files")
            if not files:
                raise ValueError(f"{path} has no files")
            for name, _, data in files:
                if data is None:
                    raise ValueError(f"{name} is larger than {max_bytes // (1024 * 1024)} MB")
                yield name, data

    def has_file(self, path: str) -> bool:
        """whether something is at path (below MOUNT_PATH) already, a file or a folder. no volume, or the root: nothing.
        ValueError for a path that leaves the files (clean_path)"""
        path = self.clean_path(path)
        return bool(path) and self._output(["test", "-e", posixpath.join(MOUNT_PATH, path)]) is not None

    def exists(self) -> bool:
        from docker.errors import NotFound
        try:
            _client().volumes.get(self.name)
            return True
        except NotFound:
            return False

    @classmethod
    def all(cls, user_id: int | None = None) -> list["SandboxVolume"]:
        """the volumes there are, of one user (None = all users)"""
        filters = {"label": [LABEL] + ([f"user_id={int(user_id)}"] if user_id is not None else [])}
        return [cls(volume.attrs["Labels"]["user_id"], volume.attrs["Labels"]["contact_id"])
                for volume in _client().volumes.list(filters=filters)]

    def _mount(self, read_only: bool = False):
        """the mount of the volume, created with its labels on first use. read only: never created, check exists() first"""
        from docker.types import Mount
        if not read_only and not self.exists():
            _client().volumes.create(self.name, labels={LABEL: "1", "user_id": str(self.user_id),
                                                        "contact_id": str(self.contact_id)})
        return Mount(target=MOUNT_PATH, source=self.name, type="volume", read_only=read_only)

    @contextmanager
    def _reader(self, command: list[str] | None = None, read_only: bool = True):
        """a created (not started) container with the volume at MOUNT_PATH (read only unless read_only False), no network,
        removed when the block ends. get_archive and put_archive work on it as it is, a command (find) needs start()"""
        container = _client().containers.create(SANDBOX_IMAGE, command, mounts=[self._mount(read_only=read_only)],
                                                user=SANDBOX_USER, network_disabled=True, mem_limit="128m",
                                                labels={LABEL: "reader"})
        try:
            yield container
        finally:
            container.remove(force=True)

    def _run(self, command: list[str]) -> None:
        """command in a reader container with the volume writable (made on first use), as SANDBOX_USER.
        OSError with its error output when it fails"""
        with self._reader(command, read_only=False) as container:
            container.start()
            status = container.wait(timeout=READER_TIMEOUT)
            if status.get("StatusCode"):
                error = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace").strip()
                raise OSError(error or f"{command[0]} failed")

    def _output(self, command: list[str], read_only: bool = True) -> bytes | None:
        """the stdout of command in a reader container, None when it failed. read only without a volume: None"""
        if read_only and not self.exists():
            return None
        with self._reader(command, read_only=read_only) as container:
            container.start()
            status = container.wait(timeout=READER_TIMEOUT)
            output = container.logs(stdout=True, stderr=False)
        return None if status.get("StatusCode") else output

    def entries(self, path: str = "") -> list[dict]:
        """the folder's files and folders [{"name", "path", "type" file|dir|link, "size", "modified" epoch}], folders
        first. no volume (nothing written yet) is an empty folder, FileNotFoundError when the folder isn't there"""
        path = self.clean_path(path)
        if not self.exists():
            if path:
                raise FileNotFoundError(path)
            return []
        folder = posixpath.join(MOUNT_PATH, path) if path else MOUNT_PATH
        # -P (the default): links are listed, never followed
        output = self._output(["find", folder, "-mindepth", "1", "-maxdepth", "1", "-printf", FIND_FORMAT])
        if output is None:
            raise FileNotFoundError(path)
        return sorted(self._parse_entries(output, path), key=lambda entry: (entry["type"] != "dir", entry["name"].lower()))

    def info(self, path: str) -> Optional[dict]:
        """the entry of path like the ones of entries, the root is a folder. None when nothing is there"""
        path = self.clean_path(path)
        if not path:
            return {"name": "", "path": "", "type": "dir", "size": 0, "modified": 0}
        output = self._output(["find", posixpath.join(MOUNT_PATH, path), "-maxdepth", "0", "-printf", FIND_FORMAT])
        entries = self._parse_entries(output or b"", posixpath.dirname(path))
        return entries[0] if entries else None

    @staticmethod
    def _parse_entries(output: bytes, folder: str) -> list[dict]:
        """the entries of find's FIND_FORMAT lines of the files in folder (a clean_path)"""
        kinds = {"d": "dir", "f": "file", "l": "link"}
        entries = []
        for line in output.decode("utf-8", errors="replace").split("\0"):
            if line.count("\t") < 3:
                continue
            kind, size, modified, name = line.split("\t", 3)
            entries.append({"name": name, "path": posixpath.join(folder, name) if folder else name,
                            "type": kinds.get(kind, "other"), "size": int(size) if kind != "d" else 0,
                            "modified": int(float(modified))})
        return entries

    def has_project(self) -> bool:
        """whether the files hold the user's work: anything not hidden in PROJECTS or WORKDIR (of any conversation).
        False without a volume"""
        output = self._output(["sh", "-c", f"find {MOUNT_PATH}/{PROJECTS} {MOUNT_PATH}/{WORKDIR} -mindepth 1 "
                                            "-not -name '.*' -print -quit 2>/dev/null; true"])
        return bool((output or b"").strip())

    def projects(self) -> list[tuple[str, str]]:
        """(folder name, first line of its PROJECT_FILE or "") of every project in PROJECTS, by name. [] without a volume"""
        script = (f'for d in {MOUNT_PATH}/{PROJECTS}/*/; do [ -d "$d" ] || continue; '
                  f'printf "%s\\t%s\\0" "$(basename "$d")" "$(head -n 1 "${{d}}{PROJECT_FILE}" 2>/dev/null | cut -c1-200)"; done')
        output = self._output(["sh", "-c", script]) or b""
        projects = [tuple(line.split("\t", 1)) for line in output.decode("utf-8", errors="replace").split("\0") if "\t" in line]
        return sorted(((name, first.strip().lstrip("#").strip()) for name, first in projects), key=lambda p: p[0].lower())

    @staticmethod
    def project_name(text: str) -> str:
        """a project's folder name from text (a name or a path, its last part): short, lowercase, letters, digits and _"""
        name = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()).strip("_")
        return name[:MAX_PROJECT_NAME].rstrip("_") or "project"

    def reserve_project(self, name: str) -> str:
        """a new project's folder in PROJECTS, made now so no other job takes it: project_name(name), on a clash name_2,
        name_3 ... (mkdir without -p, an existing folder is never reused). returns the folder's name. no volume yet: no
        project can clash, the name as it is (the first sandbox makes the files, a reader can't write a new volume's
        root). OSError when no folder could be made"""
        name = self.project_name(name)
        if not self.exists():
            return name
        candidates = [name] + [f"{name}_{i}" for i in range(2, MAX_PROJECT_TRIES + 1)]
        script = (f'mkdir -p {MOUNT_PATH}/{PROJECTS} && cd {MOUNT_PATH}/{PROJECTS} && '
                  'for n in "$@"; do mkdir -- "$n" 2>/dev/null && { printf %s "$n"; exit 0; }; done; exit 1')
        output = self._output(["sh", "-c", script, "sh", *candidates], read_only=False)
        if not output:
            raise OSError(f"no free project folder for {name}")
        return output.decode("utf-8", errors="replace").strip()

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

    def open_file(self, path: str) -> BinaryIO:
        """one regular file to read like read_file, closing it removes its reader container"""
        _, _, chunks = self.read_file(path)
        return io.BufferedReader(_ChunkReader(chunks), CHUNK)

    def write_file(self, path: str, data: bytes) -> str:
        """an AI tool's write of data (upload). returns path"""
        return self.upload(path, io.BytesIO(data), len(data))

    def upload(self, path: str, source: BinaryIO, size: int) -> str:
        """writes size bytes of source as the file path (a clean_path, its folders made), owned by SANDBOX_USER, through
        a reader container with the volume writable. an existing file is replaced. returns path"""
        path = self.clean_path(path)
        if not path:
            raise ValueError("no file name")
        now = time.time()
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES) as archive:
            with tarfile.open(fileobj=archive, mode="w") as tar:
                parts = path.split("/")
                for depth in range(1, len(parts)):
                    folder = tarfile.TarInfo("/".join(parts[:depth]))
                    folder.type, folder.mode, folder.mtime = tarfile.DIRTYPE, 0o755, now
                    folder.uid = folder.gid = SANDBOX_UID
                    tar.addfile(folder)
                member = tarfile.TarInfo(path)
                member.size, member.mode, member.mtime = size, 0o644, now
                member.uid = member.gid = SANDBOX_UID
                tar.addfile(member, source)
            archive.seek(0)
            with self._reader(read_only=False) as container:
                if not container.put_archive(MOUNT_PATH, archive):
                    raise OSError(f"{path} could not be written")
        return path

    @classmethod
    def _at(cls, path: str) -> str:
        """the absolute path of path (a clean_path) in a container, ValueError for the root"""
        path = cls.clean_path(path)
        if not path:
            raise ValueError("not the root of the files")
        return posixpath.join(MOUNT_PATH, path)

    def make_folder(self, path: str) -> None:
        """a new folder at path, its parent must be there. OSError when it can't be made"""
        self._run(["mkdir", "--", self._at(path)])

    def delete(self, path: str) -> None:
        """the file or folder at path with everything in it, the user's own change. never the root"""
        self._run(["rm", "-rf", "--", self._at(path)])

    def move(self, source: str, target: str) -> None:
        """source to target, what is at target replaced. never the root"""
        self._run(["sh", "-c", 'rm -rf -- "$2" && mv -T -- "$1" "$2"', "sh", self._at(source), self._at(target)])

    def copy(self, source: str, target: str, skip: Iterable[str] = ()) -> None:
        """source to target with everything in it (times and modes kept), what is at target replaced. never the root.
        skip: names of files and folders in a copied folder that are left out, at any depth"""
        script = ('src=$1 dst=$2; shift 2; rm -rf -- "$dst" || exit 1; '
                  'if [ -d "$src" ] && [ ! -L "$src" ]; then '
                  'mkdir -- "$dst" && tar -C "$src" -cf - --no-wildcards "$@" . | tar -C "$dst" -xpf -; '
                  'else cp -a -T -- "$src" "$dst"; fi')
        self._run(["sh", "-c", script, "sh", self._at(source), self._at(target), *(f"--exclude={name}" for name in skip)])

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
        top = posixpath.basename(path) or "files"
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

    def _own(self, container, layout: bool = False) -> None:
        """hands every file to SANDBOX_USER: a new volume belongs to root, and so do the files a root run_code wrote.
        layout: the LAYOUT folders are made first"""
        folders = " ".join(f"{MOUNT_PATH}/{folder}" for folder in LAYOUT)
        container.exec_run(["sh", "-c", (f"mkdir -p {folders} && " if layout else "") + f"chown -R {SANDBOX_USER} {MOUNT_PATH}"],
                           user="root")

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
            self._own(session.container, layout=True)
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
                logger.info(f"files of contact {self.contact_id} removed")
            except NotFound:
                pass
        except Exception as e:
            logger.error(f"files of contact {self.contact_id} not removed {repr(e)}")


def _zip_info(name: str, member: tarfile.TarInfo) -> zipfile.ZipInfo:
    """a zip entry with the tar member's time and permissions (zip times start in 1980)"""
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

    def close(self) -> None:
        """a generator of chunks is closed too: its reader container goes (read_file)"""
        if not self.closed and hasattr(self._chunks, "close"):
            self._chunks.close()
        super().close()
