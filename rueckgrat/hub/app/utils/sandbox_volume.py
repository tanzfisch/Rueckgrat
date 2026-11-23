"""the persistent sandbox files of one contact: a docker named volume, mounted at MOUNT_PATH into the bash
sandboxes of all the contact's conversations, so projects outlive a conversation. a named volume and not a hub folder:
the containers are started through the host's docker.sock, a bind path would be a host path. the contact's sandbox
container (SandboxContainer) has it mounted for good, readers and backups for one call. removed with the contact,
or by the maintenance (ConversationVolumeMaintenanceTask) when the contact is gone or after STALE_DAYS without a message
in any of its conversations. the user browses and downloads them through a short lived reader container
(SandboxVolume.entries, read_file, write_zip, files): the hub has no volume mounted. the user's own changes (the
WebDAV share, sandbox_dav) go through reader containers too (upload, make_folder, delete, move, copy).

the backup (snapshot, restore): a second volume of the contact the hub alone mounts, the agent never reaches it:
  latest/ the files before the last agent job worker that changes files (snapshot), what a files reset brings back.
          files of more than BACKUP_MAX_MB (HUB_SANDBOX_BACKUP_MAX_MB, 0 no limit) are not kept, the one before stays
  safety/ the files a files reset replaced (restore)

the layout (LAYOUT, made when the sandbox container is made):
  projects/<name>/        one folder per project, its PROJECT.md says what it is, its status and how to run it
  workdir/<conversation>/ where bash of a conversation starts, its scratch work
  data/documents/<hash>/  the files write_file writes, <hash> of the content: a write never overwrites another
  data/images/            generated images
  data/tts/               generated text to speach files
  .cache/rueckgrat/shell/<conversation>/  the bash terminal of a conversation (its folder, variables, functions)
  .cache/rueckgrat/apt-packages           the packages sudo apt installed in the sandbox container (the image writes it)"""
import hashlib
import os
import io
import posixpath
import re
import tarfile
import tempfile
import time
import zipfile
from contextlib import contextmanager, ExitStack
from typing import BinaryIO, Iterable, Iterator, Optional

from app.common import get_logger
from app.utils.text_files import sanitize_relative_path
logger = get_logger()

MOUNT_PATH = "/home"
SANDBOX_USER = "1000:1000"      # owns the files, the bash tool runs as it
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
APT_PACKAGES = ".cache/rueckgrat/apt-packages"   # one package a line, apt's Post-Invoke writes it (rueckgrat/sandbox/Dockerfile)
HASH_CHARS = 12         # of the sha256 of a document's (or audio file's) content, its folder in DOCUMENTS (TTS)
# the image of the bash sandbox and the reader containers (rueckgrat/sandbox/Dockerfile, built by compose): the python
# sandbox with C and C++ builds (cmake, ninja), it has find
SANDBOX_IMAGE = "rueckgrat-sandbox:latest"
MAX_PROJECT_NAME = 40   # characters of a project's folder name (project_name)
MAX_PROJECT_TRIES = 99  # a new project's folder: its name, then name_2 up to name_<this> (reserve_project)
READER_TIMEOUT = 30     # seconds for listing a folder
BACKUP_TIMEOUT = 600    # seconds for copying all files into or out of the backup
BACKUP_LATEST = "/backup/latest"
BACKUP_SAFETY = "/backup/safety"
BACKUP_MAX_MB = int(os.environ.get("HUB_SANDBOX_BACKUP_MAX_MB") or 0)  # files larger are not kept (snapshot), 0 no limit
# the copies of the backup's helper container (_backup): as root, ownership, modes and times kept
SNAPSHOT_SCRIPT = (f"rm -rf /backup/next && mkdir -p /backup/next && cp -a {MOUNT_PATH}/. /backup/next/ "
                   f"&& rm -rf {BACKUP_LATEST} && mv /backup/next {BACKUP_LATEST}")
LIMIT_SCRIPT = (f"s=$(du -sm {MOUNT_PATH} | cut -f1); [ \"$s\" -le {{limit}} ] "
                f"|| {{{{ echo \"the files are $s MB, more than the backup limit of {{limit}} MB\" >&2; exit 4; }}}}; ")
NO_SNAPSHOT = 3         # the exit code of RESTORE_SCRIPT without a snapshot
RESTORE_SCRIPT = (f"[ -d {BACKUP_LATEST} ] || exit {NO_SNAPSHOT}; rm -rf {BACKUP_SAFETY} && mkdir -p {BACKUP_SAFETY} "
                  f"&& cp -a {MOUNT_PATH}/. {BACKUP_SAFETY}/ && find {MOUNT_PATH} -mindepth 1 -delete "
                  f"&& cp -a {BACKUP_LATEST}/. {MOUNT_PATH}/")
CHUNK = 64 * 1024
SPOOL_BYTES = 32 * 1024 * 1024     # an upload's tar is kept in memory up to this size, on disk beyond
# a find -printf line of entries and info, \0 ends it: a name may hold tabs and newlines
FIND_FORMAT = "%y\\t%s\\t%T@\\t%f\\0"
# left out of a zip on request: version control, caches and installed packages, not the user's work
EXCLUDED = frozenset({".git", ".cache", ".local", ".npm", "__pycache__", "node_modules", ".venv", "venv"})
# the type bits of go's os.FileMode in get_archive's stat: dir, symlink, device, named pipe, socket, char device, irregular
_NOT_A_FILE = (1 << 31) | (1 << 27) | (1 << 26) | (1 << 25) | (1 << 24) | (1 << 21) | (1 << 19)


def docker_client():
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
        """the folder a conversation's bash starts in, absolute"""
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
            docker_client().volumes.get(self.name)
            return True
        except NotFound:
            return False

    @classmethod
    def all(cls, user_id: int | None = None) -> list["SandboxVolume"]:
        """the volumes there are, of one user (None = all users)"""
        filters = {"label": [f"{LABEL}=1"] + ([f"user_id={int(user_id)}"] if user_id is not None else [])}
        return [cls(volume.attrs["Labels"]["user_id"], volume.attrs["Labels"]["contact_id"])
                for volume in docker_client().volumes.list(filters=filters)]

    @property
    def backup_name(self) -> str:
        return f"rueckgrat-backup-contact-{self.contact_id}"

    def mount(self, read_only: bool = False):
        """the mount of the volume, created with its labels on first use. read only: never created, check exists() first"""
        from docker.types import Mount
        if not read_only and not self.exists():
            docker_client().volumes.create(self.name, labels={LABEL: "1", "user_id": str(self.user_id),
                                                        "contact_id": str(self.contact_id)})
        return Mount(target=MOUNT_PATH, source=self.name, type="volume", read_only=read_only)

    @contextmanager
    def _reader(self, command: list[str] | None = None, read_only: bool = True):
        """a created (not started) container with the volume at MOUNT_PATH (read only unless read_only False), no network,
        removed when the block ends. get_archive and put_archive work on it as it is, a command (find) needs start()"""
        container = docker_client().containers.create(SANDBOX_IMAGE, command, mounts=[self.mount(read_only=read_only)],
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

    def stats(self, path: str = "") -> dict[str, tuple[int, int]]:
        """{path below MOUNT_PATH: (size, mtime)} of every file below the folder path (or of the file), without their
        bytes: what an agent job's worker changed (Worker._changed). exclude, links, no volume, FileNotFoundError: like files"""
        path = self.clean_path(path)
        return {"/".join([part for part in (path, *parts) if part]): (member.size, int(member.mtime))
                for parts, member, _ in self._walk(path, True) if member.isfile()}

    def own(self, container) -> None:
        """makes the LAYOUT folders and hands every file to SANDBOX_USER, in a just made container (SandboxContainer): a
        new volume belongs to root, and so may files of an older hub"""
        folders = " ".join(f"{MOUNT_PATH}/{folder}" for folder in LAYOUT)
        container.exec_run(["sh", "-c", f"mkdir -p {folders} && chown -R {SANDBOX_USER} {MOUNT_PATH}"], user="root")

    def snapshot(self) -> None:
        """copies the files into the backup (BACKUP_LATEST, the one before goes). no volume: nothing to keep.
        OSError when the copy fails or the files are larger than BACKUP_MAX_MB (the one before stays)"""
        if self.exists():
            self._backup((LIMIT_SCRIPT.format(limit=BACKUP_MAX_MB) if BACKUP_MAX_MB > 0 else "") + SNAPSHOT_SCRIPT)
            logger.info(f"files of contact {self.contact_id} kept in the backup")

    def restore(self) -> None:
        """replaces the files with the backup's (BACKUP_LATEST), the replaced ones kept in BACKUP_SAFETY. the files must
        not change meanwhile: SandboxContainer.stop_processes first. FileNotFoundError without a backup, OSError when the
        copy fails"""
        from docker.errors import NotFound
        try:
            docker_client().volumes.get(self.backup_name)
        except NotFound:
            raise FileNotFoundError("no backup of the files")
        self._backup(RESTORE_SCRIPT)
        logger.info(f"files of contact {self.contact_id} restored from the backup")

    def _backup(self, script: str) -> None:
        """script as root in a helper container with the volume at MOUNT_PATH and the backup volume (made on first use)
        at /backup, no network, the capabilities a copy that keeps owners needs. FileNotFoundError for NO_SNAPSHOT,
        OSError with its error output when it fails otherwise"""
        from docker.errors import NotFound
        from docker.types import Mount
        client = docker_client()
        try:
            client.volumes.get(self.backup_name)
        except NotFound:
            client.volumes.create(self.backup_name, labels={LABEL: "backup", "user_id": str(self.user_id),
                                                            "contact_id": str(self.contact_id)})
        container = client.containers.create(SANDBOX_IMAGE, ["sh", "-c", script], user="root", network_disabled=True,
                                             mounts=[self.mount(), Mount(target="/backup", source=self.backup_name, type="volume")],
                                             cap_drop=["ALL"], cap_add=["CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID"],
                                             labels={LABEL: "backup"})
        try:
            container.start()
            code = container.wait(timeout=BACKUP_TIMEOUT).get("StatusCode")
            if code == NO_SNAPSHOT:
                raise FileNotFoundError("no backup of the files")
            if code:
                raise OSError(container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace").strip() or "copy failed")
        finally:
            container.remove(force=True)

    def remove(self) -> None:
        """the files, their backup and the contact's sandbox container. what isn't there, or no docker, is nothing to remove"""
        from app.utils.sandbox_container import SandboxContainer
        try:
            from docker.errors import NotFound
            SandboxContainer(self).remove()
            for name in (self.name, self.backup_name):
                try:
                    docker_client().volumes.get(name).remove(force=True)
                except NotFound:
                    pass
            logger.info(f"files of contact {self.contact_id} removed")
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
