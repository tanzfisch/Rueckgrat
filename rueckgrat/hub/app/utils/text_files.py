"""text files the write_file tool attaches to one assistant message: written by the AI (content), or copied from the
conversation's sandbox files (attach), those may be binary.

on disk only a hashed name, under files/<user_id>/<conversation_id>/<message_id>/, one file per write_file call.
the real path the AI wrote lives in the db. a later message has its own folder, so it never overwrites this one.
"""
import hashlib
import re
from pathlib import Path

from app.common import get_logger
logger = get_logger()

FILES_ROOT = Path("/hub/files")
MAX_FILE_BYTES = 256 * 1024             # a file the AI writes into the call
MAX_ATTACH_BYTES = 10 * 1024 * 1024     # a file copied from the sandbox files
_SEGMENT = re.compile(r"[^\x00-\x1f\\/:*?\"<>|]+")
_STORED = re.compile(r"^[0-9a-f]{64}(?:\.[a-z0-9]{1,8})?$")

MIME = {
    "html": "text/html", "htm": "text/html", "css": "text/css",
    "js": "text/javascript", "mjs": "text/javascript",
    "json": "application/json", "md": "text/markdown", "txt": "text/plain",
    "py": "text/x-python", "svg": "image/svg+xml", "xml": "application/xml",
    "csv": "text/csv", "ts": "text/typescript", "tsx": "text/tsx", "jsx": "text/jsx",
}


def sanitize_relative_path(path: str) -> str | None:
    """a relative path like css/style.css, or None when it leaves the message folder"""
    if not isinstance(path, str):
        return None
    text = path.strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None
    parts = []
    for part in text.split("/"):
        if part in ("", ".", "..") or part.startswith("."):
            return None
        if not _SEGMENT.fullmatch(part) or len(part) > 80:
            return None
        parts.append(part)
    if not parts or len(parts) > 8:
        return None
    real = "/".join(parts)
    return real if len(real) <= 180 else None


def check_file(path: str, content: str | bytes) -> tuple[str, bytes]:
    """(the real relative path, the bytes) of a valid file, ValueError if it is not one. content str: text the AI
    wrote, at most MAX_FILE_BYTES. bytes: a file copied from the sandbox files, also binary, at most MAX_ATTACH_BYTES"""
    real = sanitize_relative_path(path)
    if not real or not isinstance(content, (str, bytes)):
        raise ValueError(f"invalid file {path!r}")
    data, limit = (content.encode("utf-8"), MAX_FILE_BYTES) if isinstance(content, str) else (content, MAX_ATTACH_BYTES)
    if isinstance(content, str) and b"\0" in data:
        raise ValueError(f"{real} is not plain text")
    if len(data) > limit:
        raise ValueError(f"{real} is larger than {limit} bytes")
    return real, data


def is_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _extension(real_name: str) -> str:
    base = real_name.rsplit("/", 1)[-1]
    if "." not in base:
        return ".txt"
    ext = base.rsplit(".", 1)[-1].lower()
    return f".{ext}" if re.fullmatch(r"[a-z0-9]{1,8}", ext) else ".txt"


def mime_type(real_name: str, data: bytes | None = None) -> str:
    """by the extension, text/plain when unknown. binary data is application/octet-stream: an image/ type would make
    the chat take the file for an image of the image store"""
    if data is not None and not is_text(data):
        return "application/octet-stream"
    ext = _extension(real_name)[1:]
    return MIME.get(ext, "text/plain")


def stored_name_for(real_name: str, data: bytes) -> str:
    """sha256 of the real path and the bytes, plus a safe extension. the path is part of the
    hash so two files in one message cannot land on the same disk name"""
    digest = hashlib.sha256(real_name.encode("utf-8") + b"\0" + data).hexdigest()
    return digest + _extension(real_name)


def message_dir(user_id: int, conversation_id: int, message_id: int, root: Path = FILES_ROOT) -> Path:
    return Path(root) / str(int(user_id)) / str(int(conversation_id)) / str(int(message_id))


def _inside(root: Path, path: Path) -> bool:
    root = root.resolve()
    path = path.resolve()
    return path == root or root in path.parents


def write_blob(user_id: int, conversation_id: int, message_id: int, stored_name: str, data: bytes,
               root: Path = FILES_ROOT) -> Path:
    if not _STORED.fullmatch(stored_name):
        raise ValueError(f"refusing stored name {stored_name!r}")
    directory = message_dir(user_id, conversation_id, message_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / stored_name
    if not _inside(Path(root), path):
        raise ValueError("refusing to write outside the files root")
    path.write_bytes(data)
    return path


def remove_message_files(user_id: int, conversation_id: int, message_id: int, root: Path = FILES_ROOT) -> None:
    directory = message_dir(user_id, conversation_id, message_id, root)
    if _inside(Path(root), directory) and directory.is_dir():
        for child in sorted(directory.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        directory.rmdir()


def remove_conversation_files(user_id: int, conversation_id: int, root: Path = FILES_ROOT) -> None:
    directory = Path(root) / str(int(user_id)) / str(int(conversation_id))
    if not (_inside(Path(root), directory) and directory.is_dir()):
        return
    for child in sorted(directory.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    directory.rmdir()


def payloads_for_messages(db, message_ids: list[int]) -> dict[int, list[dict]]:
    """message id -> the file cards the chat shows, one per file"""
    rows = db.get_message_files_for_messages(message_ids)
    return {message_id: [{
                "file_name": row["real_name"],
                "stored_name": row["stored_name"],
                "file_type": row["file_type"],
                "file_size": row["file_size"],
            } for row in group]
            for message_id, group in rows.items()}


def attach_message_file(db, user_id: int, conversation_id: int, message_id: int, path: str, content: str | bytes,
                        root: Path = FILES_ROOT) -> dict:
    """writes one file for this message id and records its real name. returns the chat payload. content: see check_file"""
    real, data = check_file(path, content)
    stored = stored_name_for(real, data)
    file_type = mime_type(real, data)
    write_blob(user_id, conversation_id, message_id, stored, data, root)
    db.add_message_file(user_id, conversation_id, message_id, real, stored, file_type, len(data))
    db.add_attachment(message_id, real, f"files/{int(user_id)}/{int(conversation_id)}/{int(message_id)}/{stored}",
                      file_type, len(data))
    logger.info(f"attached {real} to message {message_id}")
    return {
        "file_name": real,
        "stored_name": stored,
        "file_type": file_type,
        "file_size": len(data),
    }
