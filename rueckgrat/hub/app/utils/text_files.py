"""text files the write_file tool attaches to one assistant message.

on disk only a hashed name, under files/<user_id>/<conversation_id>/<message_id>/.
one file stays itself. several files of that message are one zip, and the originals
are not also kept beside it: the zip is the download, the real paths live in the db
and inside the archive. a later message has its own folder, so it never overwrites this one.
"""
import hashlib
import io
import re
import zipfile
from pathlib import Path

from app.common import get_logger
logger = get_logger()

FILES_ROOT = Path("/hub/files")
ZIP_NAME = "files.zip"
MAX_FILES = 20
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
PREVIEW_CHARS = 2000
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


def _extension(real_name: str) -> str:
    base = real_name.rsplit("/", 1)[-1]
    if "." not in base:
        return ".txt"
    ext = base.rsplit(".", 1)[-1].lower()
    return f".{ext}" if re.fullmatch(r"[a-z0-9]{1,8}", ext) else ".txt"


def mime_type(real_name: str) -> str:
    ext = _extension(real_name)[1:]
    return MIME.get(ext, "text/plain")


def stored_name_for(real_name: str, data: bytes) -> str:
    """sha256 of the real path and the bytes, plus a safe extension. the path is part of the
    hash so two files in one message cannot land on the same disk name"""
    digest = hashlib.sha256(real_name.encode("utf-8") + b"\0" + data).hexdigest()
    return digest + _extension(real_name)


def prepare_files(items: list[dict]) -> list[dict]:
    """validated files in first-seen order. the same path later in the message replaces the earlier text"""
    order, by_path = [], {}
    for item in items:
        real = sanitize_relative_path(item.get("path"))
        content = item.get("content")
        if not real or not isinstance(content, str):
            raise ValueError(f"invalid file {item.get('path')!r}")
        data = content.encode("utf-8")
        if b"\0" in data:
            raise ValueError(f"{real} is not plain text")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{real} is larger than {MAX_FILE_BYTES} bytes")
        if real not in by_path:
            order.append(real)
        by_path[real] = {"real_name": real, "data": data, "file_type": mime_type(real), "file_size": len(data)}
    files = [by_path[name] for name in order]
    if not files:
        raise ValueError("no files")
    if len(files) > MAX_FILES:
        raise ValueError(f"more than {MAX_FILES} files")
    if sum(item["file_size"] for item in files) > MAX_TOTAL_BYTES:
        raise ValueError(f"files are larger than {MAX_TOTAL_BYTES} bytes")
    return files


def _zip_bytes(files: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            info = zipfile.ZipInfo(item["real_name"])
            info.flag_bits |= 0x800    # names are utf-8
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, item["data"])
    return buffer.getvalue()


def package(items: list[dict]) -> dict:
    """one downloadable blob. a single file keeps its type; several become files.zip and are not also stored loose"""
    files = prepare_files(items)
    if len(files) == 1:
        item = files[0]
        data = item["data"]
        stored = stored_name_for(item["real_name"], data)
        display, file_type = item["real_name"], item["file_type"]
    else:
        data = _zip_bytes(files)
        stored = hashlib.sha256(data).hexdigest() + ".zip"
        display, file_type = ZIP_NAME, "application/zip"
    return {
        "display_name": display,
        "stored_name": stored,
        "file_type": file_type,
        "data": data,
        "file_size": len(data),
        "members": [{"real_name": item["real_name"], "file_type": item["file_type"], "file_size": item["file_size"],
                     "preview": item["data"].decode("utf-8")[:PREVIEW_CHARS]} for item in files],
    }


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


def _preview_from_disk(row: dict, members: list[dict], root: Path) -> list[dict]:
    path = message_dir(row["user_id"], row["conversation_id"], row["message_id"], root) / row["stored_name"]
    texts = {}
    try:
        if row["file_type"] == "application/zip":
            with zipfile.ZipFile(path) as archive:
                for member in members:
                    texts[member["real_name"]] = archive.read(member["real_name"]).decode("utf-8", "replace")[:PREVIEW_CHARS]
        else:
            texts[row["real_name"]] = path.read_bytes().decode("utf-8", "replace")[:PREVIEW_CHARS]
    except Exception as e:
        logger.warning(f"no preview for message {row['message_id']}: {e}")
    shown = members or [{"real_name": row["real_name"], "file_type": row["file_type"], "file_size": row["file_size"]}]
    return [{**member, "preview": texts.get(member["real_name"], "")} for member in shown]


def payloads_for_messages(db, message_ids: list[int], root: Path = FILES_ROOT) -> dict[int, dict]:
    """message id -> the card the chat shows. previews are read back from the stored file or zip"""
    rows = db.get_message_files_for_messages(message_ids)
    out = {}
    for message_id, group in rows.items():
        parent = next((row for row in group if row["parent_id"] is None), None)
        if parent is None:
            continue
        members = [row for row in group if row["parent_id"] == parent["id"]]
        member_payload = [{"real_name": row["real_name"], "file_type": row["file_type"], "file_size": row["file_size"]}
                          for row in members]
        out[message_id] = {
            "file_name": parent["real_name"],
            "stored_name": parent["stored_name"],
            "file_type": parent["file_type"],
            "file_size": parent["file_size"],
            "members": _preview_from_disk(parent, member_payload, root),
        }
    return out


def attach_message_files(db, user_id: int, conversation_id: int, message_id: int, items: list[dict],
                         root: Path = FILES_ROOT) -> dict:
    """writes the blob for this message id and records the real names. returns the chat payload"""
    packaged = package(items)
    write_blob(user_id, conversation_id, message_id, packaged["stored_name"], packaged["data"], root)
    parent_id = db.add_message_file(user_id, conversation_id, message_id, packaged["display_name"],
                                    packaged["stored_name"], packaged["file_type"], packaged["file_size"])
    db.add_attachment(message_id, packaged["display_name"],
                      f"files/{int(user_id)}/{int(conversation_id)}/{int(message_id)}/{packaged['stored_name']}",
                      packaged["file_type"], packaged["file_size"])
    if len(packaged["members"]) > 1:
        for member in packaged["members"]:
            db.add_message_file(user_id, conversation_id, message_id, member["real_name"], packaged["stored_name"],
                                member["file_type"], member["file_size"], parent_id=parent_id)
    logger.info(f"attached {packaged['display_name']} to message {message_id} ({len(packaged['members'])} file(s))")
    return {
        "file_name": packaged["display_name"],
        "stored_name": packaged["stored_name"],
        "file_type": packaged["file_type"],
        "file_size": packaged["file_size"],
        "members": packaged["members"],
    }
