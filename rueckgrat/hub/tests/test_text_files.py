"""write_file packaging: real paths in the zip and the db, hashed names on disk. no network."""
import io
import zipfile

from app.utils.db import ChatDB
from app.utils.text_files import (
    ZIP_NAME, attach_message_files, package, sanitize_relative_path, stored_name_for,
)


def test_paths_reject_traversal_and_keep_subfolders():
    assert sanitize_relative_path("css/style.css") == "css/style.css"
    assert sanitize_relative_path("index.html") == "index.html"
    assert sanitize_relative_path(r"css\style.css") == "css/style.css"
    for bad in ("../etc/passwd", "/etc/passwd", "css/../../x", "C:/windows", "..", "css/../style.css", "", None):
        assert sanitize_relative_path(bad) is None


def test_hashed_names_do_not_collide_for_different_files():
    a = stored_name_for("css/style.css", b"body{}")
    b = stored_name_for("js/style.css", b"body{}")
    c = stored_name_for("css/style.css", b"body{color:red}")
    assert a != b != c
    assert a.endswith(".css") and not a.startswith("css")


def test_several_files_become_one_zip_with_real_paths():
    html, css = "<h1>Hi</h1>", "body { color: #222; }"
    packed = package([
        {"path": "index.html", "content": html},
        {"path": "css/style.css", "content": css},
        {"path": "index.html", "content": "<h1>Revised</h1>"},
    ])
    assert packed["display_name"] == ZIP_NAME
    assert packed["stored_name"].endswith(".zip")
    archive = zipfile.ZipFile(io.BytesIO(packed["data"]))
    assert archive.namelist() == ["index.html", "css/style.css"]
    assert archive.read("index.html") == b"<h1>Revised</h1>"
    assert archive.read("css/style.css") == css.encode()
    assert [item["real_name"] for item in packed["members"]] == ["index.html", "css/style.css"]


def test_one_file_stays_plain_and_a_second_message_does_not_overwrite(tmp_path):
    class DB:
        def __init__(self):
            self.files, self.attachments = [], []

        def add_message_file(self, user_id, conversation_id, message_id, real_name, stored_name, file_type, file_size, parent_id=None):
            self.files.append({
                "user_id": user_id, "conversation_id": conversation_id, "message_id": message_id,
                "real_name": real_name, "stored_name": stored_name, "file_type": file_type,
                "file_size": file_size, "parent_id": parent_id,
            })
            return len(self.files)

        def add_attachment(self, message_id, file_name, file_url, file_type, file_size):
            self.attachments.append((message_id, file_name, file_url, file_type, file_size))
            return 1

    db = DB()
    one = [{"path": "css/style.css", "content": "body{}"}]
    first = attach_message_files(db, 7, 16, 41, one, root=tmp_path)
    second = attach_message_files(db, 7, 16, 42, one + [{"path": "index.html", "content": "<p>"}], root=tmp_path)

    single = tmp_path / "7" / "16" / "41"
    assert [p.name for p in single.iterdir()] == [first["stored_name"]]
    assert first["file_name"] == "css/style.css"
    assert (single / first["stored_name"]).read_bytes() == b"body{}"
    assert db.files[0]["real_name"] == "css/style.css"
    assert db.files[0]["parent_id"] is None

    both = list((tmp_path / "7" / "16" / "42").iterdir())
    assert len(both) == 1 and both[0].name == second["stored_name"] and both[0].suffix == ".zip"
    assert zipfile.ZipFile(both[0]).namelist() == ["css/style.css", "index.html"]
    names = [row["real_name"] for row in db.files if row["message_id"] == 42]
    assert names[0] == "files.zip"
    assert names[1:] == ["css/style.css", "index.html"]
    assert all(row["stored_name"] == second["stored_name"] for row in db.files if row["message_id"] == 42)
    assert db.attachments[1][1] == "files.zip"
    assert "/42/" in db.attachments[1][2] and "/41/" in db.attachments[0][2]


def test_schema_has_message_files_without_a_version_bump(tmp_path):
    db = ChatDB(str(tmp_path / "chat.db"))
    with db.get_connection() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'message_files'").fetchone()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5


def test_extract_keeps_braces_inside_a_file():
    import app.tasks.tool_detection_task  # the task package before the tools package, same as the other tests
    from app.tools.tool_registry import ToolRegistry
    registry = ToolRegistry(None, None, None)
    text = '{"tool": "write_file", "path": "js/app.js", "content": "function f() { return 1; }"}'
    calls, _ = registry.extract_tool_calls(text)
    assert calls[0]["path"] == "js/app.js"
    assert calls[0]["content"] == "function f() { return 1; }"
