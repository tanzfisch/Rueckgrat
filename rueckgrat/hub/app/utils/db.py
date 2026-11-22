import sqlite3
import json
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite_vec

from app.common import get_logger
logger = get_logger()

# no embedding model yet: 384 fits the common small sentence embedders (all-MiniLM-L6-v2, bge-small, e5-small).
# a different model with another size needs this changed and SCHEMA_VERSION bumped
MEMORY_EMBEDDING_DIM = 384
# PRAGMA user_version of a db made by this hub. bump it on every schema change: until 1.0 an older db is wiped, never migrated
SCHEMA_VERSION = 12     # 12: #227 done_with_warnings in jobs.status and job_protocols.status
# #227 an agent job that is done with warnings (steps its sandbox could not check): its own status in jobs and job_protocols
JOB_DONE_WITH_WARNINGS = "done_with_warnings"
# #174 finished job protocols older than this are deleted (at the end of a job and at hub start), they are for looking into recent jobs
PROTOCOL_RETENTION_HOURS = 24

class ChatDB:
    _read_only = False

    @classmethod
    def read_only(cls, db_path):
        """an existing db for queries only, e.g. hub management next to a running hub: no table setup, writes fail"""
        db = cls.__new__(cls)
        db.db_path = db_path
        db._read_only = True
        return db

    def __init__(self, db_path):
        self.db_path = db_path

        logger.debug(f"db path is: {db_path}")
        conn = self.get_connection()
        cursor = conn.cursor()

        version = cursor.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION and (version or cursor.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]):
            conn.close()
            logger.error(f"database {db_path} has schema version {version}, this hub needs {SCHEMA_VERSION}. "
                               f"There is no migration before 1.0: wipe the database")
            raise RuntimeError(f"database {db_path} has schema version {version}, this hub needs {SCHEMA_VERSION}. "
                               f"there is no migration before 1.0: wipe the database")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            gender TEXT CHECK(gender IN ('male', 'female')) DEFAULT NULL,
            role TEXT,
            personality TEXT,
            profile TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, name)
        );""")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            type TEXT CHECK(type IN ('profile', 'conversation_images')) DEFAULT 'profile',
            file_key TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            title TEXT DEFAULT '...',
            context TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        )""")                

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'error')),
            name TEXT,
            content TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            sources TEXT,
            data TEXT,      -- json {kind: value} a tool shows under the message, e.g. {"poll": {...}, "map": {...}}, see set_message_data

            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")

        # file_type e.g. 'image/png', 'application/pdf'
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                file_name TEXT,
                file_url TEXT,
                file_type TEXT,                
                file_size INTEGER,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT,
                email TEXT NOT NULL DEFAULT '',
                nsfw_allowed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

        # invites gate signup when the hub runs with SIGNUP_MODE=invite
        # only a sha256 of the token is stored, the plain token is shown once on creation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT UNIQUE NOT NULL,
                created_by TEXT,
                email TEXT DEFAULT NULL,
                expires_at TEXT DEFAULT NULL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                uses INTEGER NOT NULL DEFAULT 0,
                used_at TEXT DEFAULT NULL,
                used_by INTEGER DEFAULT NULL,
                nsfw_allowed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (used_by) REFERENCES users(id) ON DELETE SET NULL
        )""")

        # stay-logged-in sessions, one row per device login. only a sha256 of the token is stored: the token is
        # 256 random bits, so unlike a password it can't be guessed or brute forced from the hash and a fast
        # hash is enough. a db leak gives no usable tokens. rotated_at: swapped for a new one by /refresh, kept
        # until it expires so a second use (stolen copy) is noticed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_used_at TEXT DEFAULT NULL,
                rotated_at TEXT DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)")
        cursor.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (self._now(),))

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voices (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            contact_id INTEGER DEFAULT NULL,
            file_key TEXT NOT NULL,
            sample_rate INTEGER,
            duration REAL,
            content_hash TEXT DEFAULT NULL,
            predefined_id TEXT DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL
        )""")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
            file_key TEXT PRIMARY KEY,
            generation TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

        # images of the image generation tool, per user. the row is written when the prompt is submitted (status pending,
        # no file yet) and finished later: done + file_name (the png is in /hub/images) or failed. the client's request_id
        # matches the live result to the row. UNIQUE allows many NULL file names
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS generated_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            request_id TEXT NOT NULL DEFAULT '',
            file_name TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, file_name),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")

        # what a contact remembers (remember tool), per user and contact. the vector is in contact_memory_vectors
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        )""")

        # nearest neighbour index of the memory embeddings (sqlite-vec), one partition per contact. memory_id is contact_memories.id.
        # a virtual table can't have foreign keys: the trigger removes the vector with its memory, also in the contact/user cascade
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS contact_memory_vectors USING vec0(
            memory_id INTEGER PRIMARY KEY,
            contact_id INTEGER PARTITION KEY,
            user_id INTEGER,
            embedding FLOAT[{MEMORY_EMBEDDING_DIM}] distance_metric=cosine
        )""")
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS contact_memory_vectors_delete AFTER DELETE ON contact_memories
            BEGIN
                DELETE FROM contact_memory_vectors WHERE memory_id = OLD.id;
            END
        """)

        # #147 one summary per conversation for finding it again by meaning, made by the maintenance sweeper (app/maintenance).
        # updated_at (UTC, like messages.timestamp): when it was made, messages newer than this make it stale
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
            conversation_id INTEGER PRIMARY KEY,
            summary TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")

        # the summaries' vectors (same model and dimension as the memories), one partition per user.
        # the trigger removes the vector with its conversation, also in the contact/user cascade. memories are not touched
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS conversation_summary_vectors USING vec0(
            conversation_id INTEGER PRIMARY KEY,
            user_id INTEGER PARTITION KEY,
            contact_id INTEGER,
            embedding FLOAT[{MEMORY_EMBEDDING_DIM}] distance_metric=cosine
        )""")
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS conversation_summary_vectors_delete AFTER DELETE ON conversations
            BEGIN
                DELETE FROM conversation_summary_vectors WHERE conversation_id = OLD.id;
            END
        """)

        # per user settings. profile: the user's profile json (get_user_data). timezone: IANA name the user chose, the companion
        # plans in it (timestamps stay UTC). device_timezone: the one the app sent at login, used while timezone is NULL.
        # profile_image_key: current user avatar in /hub/images, NULL if none. tts_voice: the voice uuid (voices) the
        # text_to_speech tool speaks with, NULL: the contact's voice
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            profile TEXT,
            timezone TEXT,
            profile_image_key TEXT,
            device_timezone TEXT DEFAULT NULL,
            tts_voice TEXT DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")

        # the private calendar of a companion contact (profile "companion": true), see app/companion.
        # due_at / fired_at are UTC "YYYY-MM-DD HH:MM:SS" like CURRENT_TIMESTAMP. recurrence: see clock.RECURRENCES ('' once).
        # a recurring row stays pending and moves on after firing, result and message_id are of its last firing.
        # kind 'task' (#170) is a task of the user (task tool, /tasks), note its text: alarm rings the app, conversation_id is
        # where it was asked for (NULL: the contact's latest conversation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS companion_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            recurrence TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'missed')),
            result TEXT NOT NULL DEFAULT '',
            message_id INTEGER DEFAULT NULL,
            fired_at TEXT DEFAULT NULL,
            alarm INTEGER NOT NULL DEFAULT 0,
            conversation_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_companion_due ON companion_calendar(status, due_at)")

        # what each companion pass decided (json, see CompanionJob.log), the last COMPANION_LOG_KEEP per contact.
        # at = the companion's clock (may be simulated), created_at = the wall clock. only for hub management
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS companion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            at TEXT NOT NULL,
            record TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        )""")

        # #152 background jobs started by the spawn_job tool. id is uuid4 hex, made by the tool. started_at / finished_at are UTC
        # "YYYY-MM-DD HH:MM:SS" like CURRENT_TIMESTAMP. result is the report of what the job did, NULL until it finished.
        # result is JSON text (sqlite has no JSON column type; stored with json.dumps like messages.sources):
        # {"summary": str | null, "details": str | null}, more keys (e.g. file paths) can be added later without a migration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'initializing' CHECK (status IN ('initializing', 'running', 'done', 'done_with_warnings', 'failed', 'cancelled')),
            prompt TEXT NOT NULL,
            result TEXT DEFAULT NULL CHECK (result IS NULL OR json_valid(result)),
            conversation_id INTEGER DEFAULT NULL,
            started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT DEFAULT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")

        # #174 #215 the decision trace of an agent job, a user's task pass or a companion pass (app.agent_jobs.protocol, its
        # comment has the fields), written as it happens. id is the protocol id of hub management, job_id the job's own id
        # (jobs.id of an agent job, the AgentJob id of a pass: no jobs row, so no foreign key). kind: job / task / companion.
        # conversation_id, message_id: an agent job's conversation and the user message that started it (no foreign key: an
        # edited or deleted message keeps its job's protocol until the retention ends). report_message_id: the message that
        # told the user about it. source_id: a pass's companion_calendar row. status: running until it ends, interrupted when
        # the hub restarted while it ran. plan: JSON, the current plan only. time_limit: seconds. created_at: its start (UTC).
        # the lines, tool calls and outputs go with their protocol (ON DELETE CASCADE, also the retention)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('job', 'task', 'companion')),
            user_id INTEGER NOT NULL,
            contact_id INTEGER DEFAULT NULL,
            conversation_id INTEGER DEFAULT NULL,
            message_id INTEGER DEFAULT NULL,
            report_message_id INTEGER DEFAULT NULL,
            source_id INTEGER DEFAULT NULL,
            name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'done_with_warnings', 'failed', 'cancelled', 'interrupted')),
            plan TEXT DEFAULT NULL CHECK (plan IS NULL OR json_valid(plan)),
            time_limit INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")
        # one per action. step: the controller's step (1-based) or NULL, task: the plan's task id or NULL, ok: 1 / 0 / NULL.
        # data: JSON, the action's other fields, data.out = {field: ref} for the long texts in protocol_outputs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS protocol_lines (
            protocol_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            at TEXT NOT NULL,
            agent TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            step INTEGER DEFAULT NULL,
            task TEXT DEFAULT NULL,
            action TEXT NOT NULL,
            ok INTEGER DEFAULT NULL,
            data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)),
            PRIMARY KEY (protocol_id, seq),
            FOREIGN KEY (protocol_id) REFERENCES job_protocols(id) ON DELETE CASCADE
        )""")
        # one per tool call of a worker. call: its number in the protocol (the line's data.call). args: JSON text in full
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS protocol_tool_calls (
            protocol_id INTEGER NOT NULL,
            call INTEGER NOT NULL,
            at TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            step INTEGER DEFAULT NULL,
            task TEXT DEFAULT NULL,
            tool TEXT NOT NULL,
            args TEXT,
            ok INTEGER NOT NULL,
            error TEXT DEFAULT NULL,
            duration_ms INTEGER,
            PRIMARY KEY (protocol_id, call),
            FOREIGN KEY (protocol_id) REFERENCES job_protocols(id) ON DELETE CASCADE
        )""")
        # the long texts of a protocol in full (prompts, tasks, summaries, errors, ...), ref "o1", "o2", ... kind: the field
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS protocol_outputs (
            protocol_id INTEGER NOT NULL,
            ref TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (protocol_id, ref),
            FOREIGN KEY (protocol_id) REFERENCES job_protocols(id) ON DELETE CASCADE
        )""")

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_voices_contact
            ON voices(contact_id) WHERE contact_id IS NOT NULL
        """)

        # text files of write_file. real_name is the path the AI wrote (css/style.css).
        # stored_name is the hashed file in files/<user_id>/<conversation_id>/<message_id>/.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conversation_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            real_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES message_files(id) ON DELETE CASCADE
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_files_message ON message_files(message_id)")

        # #198 the recordings of the transcribe app, per user. duration: seconds recorded so far.
        # a segment is the text of one utterance, a bookmark the moment it was tapped, both in seconds of the recording
        # (only to place the bookmark in the text and to skip audio sent twice, the audio is not kept). label: the user's name for it.
        # text stays as recognised (voice commands are read from it), edited: the user's text for the segment, NULL if not edited.
        # kind 'heading': a heading the user added after the recording, text its words, start = end between its neighbours.
        # title: '' = the app names it by its date, an enhanced copy is named after its original.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            language TEXT NOT NULL DEFAULT '',
            duration REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            title TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id INTEGER NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            text TEXT NOT NULL,
            edited TEXT DEFAULT NULL,
            kind TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE
        )""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transcript_bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id INTEGER NOT NULL,
            at_time REAL NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE
        )""")
        # sqlite does not index foreign keys by itself: the lookups by conversation, contact and message
        for index, table_columns in (
            ("idx_messages_conversation", "messages(conversation_id)"),
            ("idx_conversations_contact", "conversations(user_id, contact_id)"),
            ("idx_attachments_message", "attachments(message_id)"),
            ("idx_contact_images_contact", "contact_images(contact_id)"),
            ("idx_contact_memories_contact", "contact_memories(user_id, contact_id)"),
            ("idx_companion_log_contact", "companion_log(contact_id)"),
            ("idx_jobs_conversation", "jobs(conversation_id)"),
            ("idx_job_protocols_user", "job_protocols(user_id)"),
            ("idx_transcripts_user", "transcripts(user_id)"),
            ("idx_transcript_segments_transcript", "transcript_segments(transcript_id)"),
            ("idx_transcript_bookmarks_transcript", "transcript_bookmarks(transcript_id)"),
        ):
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {index} ON {table_columns}")

        cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        conn.close()

        logger.info("Database initialized")

    def get_connection(self):
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) if self._read_only else sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        # on every connection: the delete trigger needs vec0 wherever contacts, users or memories are deleted
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception as e:
            logger.error(f"failed loading sqlite-vec, no memory vector index: {e}")
        conn.row_factory = sqlite3.Row
        return conn

    def create_user(self, username: str, passwd: str = None, nsfw_allowed: bool = False) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password, nsfw_allowed) VALUES (?, ?, ?)",
                    (username, passwd, 1 if nsfw_allowed else 0)
                )
                conn.commit()
                logger.info("created user")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                logger.error("Username already exists")

    def remove_user(self, user_name: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE username = ?", (user_name,))
            conn.commit()

    def remove_user_by_id(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        
    def get_user(self, user_name: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, password, nsfw_allowed, created_at FROM users WHERE username = ?",
                (user_name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None 

    def update_password(self, user_id: int, passwd: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE users SET password = ? WHERE id = ?", (passwd, user_id))
            conn.commit()
            return cursor.rowcount == 1

    ########### refresh tokens (stay logged in)
    def add_refresh_token(self, user_id: int, token: str, days: float) -> None:
        now = datetime.now(timezone.utc)
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, self._hash_token(token), now.isoformat(timespec="seconds"),
                 (now + timedelta(days=days)).isoformat(timespec="seconds")))
            conn.commit()

    def rotate_refresh_token(self, token: str, new_token: str, days: float, reuse_grace_seconds: float = 30) -> tuple[int | None, str]:
        """swaps a valid refresh token for new_token (new expiry: sliding window).
        returns (user_id, "ok") or (None, reason): "unknown", "expired", "reused" (all of the user's sessions
        were revoked: an already rotated token came back, so someone else has a copy) or "retry" (rotated
        within the last reuse_grace_seconds, e.g. a retried request: refused, nothing revoked)"""
        now = datetime.now(timezone.utc)
        now_s = now.isoformat(timespec="seconds")
        with self.get_connection() as conn:
            # one writer at a time: two refreshes with the same token can't both win
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (now_s,))
            row = conn.execute("SELECT id, user_id, expires_at, rotated_at FROM refresh_tokens WHERE token_hash = ?",
                               (self._hash_token(token),)).fetchone()
            if not row:
                conn.commit()
                return None, "unknown"
            if row["rotated_at"]:
                rotated = datetime.fromisoformat(row["rotated_at"])
                if (now - rotated).total_seconds() <= reuse_grace_seconds:
                    conn.commit()
                    return None, "retry"
                conn.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (row["user_id"],))
                conn.commit()
                return None, "reused"
            if row["expires_at"] < now_s:
                conn.execute("DELETE FROM refresh_tokens WHERE id = ?", (row["id"],))
                conn.commit()
                return None, "expired"
            conn.execute("UPDATE refresh_tokens SET rotated_at = ?, last_used_at = ? WHERE id = ?", (now_s, now_s, row["id"]))
            conn.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, created_at, expires_at, last_used_at) VALUES (?, ?, ?, ?, ?)",
                (row["user_id"], self._hash_token(new_token), now_s, (now + timedelta(days=days)).isoformat(timespec="seconds"), now_s))
            conn.commit()
            return row["user_id"], "ok"

    def delete_refresh_token(self, user_id: int, token: str) -> bool:
        """logout of one device. only the user's own token"""
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM refresh_tokens WHERE user_id = ? AND token_hash = ?", (user_id, self._hash_token(token)))
            conn.commit()
            return cursor.rowcount > 0

    def delete_refresh_tokens(self, user_id: int) -> int:
        """logs every device of the user out (password change)"""
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount

    def get_email(self, user_id: int) -> str:
        with self.get_connection() as conn:
            row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            return row["email"] if row else ""

    def set_email(self, user_id: int, email: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
            conn.commit()
            return cursor.rowcount == 1

    def user_nsfw_allowed(self, user_id: int) -> bool:
        """
        True only if the user's account (copied from their invite) allows NSFW. Unknown user = False (SFW).
        """
        with self.get_connection() as conn:
            row = conn.execute("SELECT nsfw_allowed FROM users WHERE id = ?", (user_id,)).fetchone()
            return bool(row and row["nsfw_allowed"])

    def get_user_id(self, user_name: str):
        """
        Retrieve the user ID for a given username.
        Returns the ID if found, otherwise None.
        """

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM users WHERE username = ?",
                (user_name,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_user_by_id(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, password, nsfw_allowed, created_at FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None            
        
    def get_users(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, created_at FROM users")
            return [dict(row) for row in cursor.fetchall()]        

    def update_user_data(self, user_id: int, user_data: dict) -> bool:
        """stores the user's profile (user_data["profile"], json text), the other settings stay"""
        if "profile" not in user_data:
            return False
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("""
                    INSERT INTO user_settings (user_id, profile) VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET profile = excluded.profile
                """, (user_id, user_data["profile"]))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed updating user data {e}")
                return False

    def get_user_data(self, user_id: int) -> dict | None:
        """{"profile": json text}, None without a profile"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT profile FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return {"profile": row[0]} if row and row[0] is not None else None

    def create_contact(self, user_id: int, contact_name: str) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO contacts (user_id, name, profile)
                    VALUES (?, ?, '{}')
                """, (user_id, contact_name))

                conn.commit()
                return cursor.lastrowid
            
            except Exception as e:
                logger.error(f"failed creating contact: {e}")
                
        return -1    

    def save_image_generation(self, file_key: str, generation: dict) -> bool:
        """stores everything that went into an image (prompts, seed, model, size, steps, cfg ...) as json"""
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO images (file_key, generation)
                    VALUES (?, ?)
                """, (file_key, json.dumps(generation)))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Failed saving generation for image {file_key}: {e}")
        return False

    def get_image_generation(self, file_key: str) -> dict | None:
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT generation FROM images WHERE file_key = ?", (file_key,)).fetchone()
                return json.loads(row[0]) if row else None
            except Exception as e:
                logger.error(f"Failed reading generation for image {file_key}: {e}")
        return None

    def add_generated_image_pending(self, user_id: int, prompt: str, request_id: str) -> int:
        """a prompt of the image tool was submitted. returns the row id (0 if it could not be saved)"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO generated_images (user_id, prompt, request_id) VALUES (?, ?, ?)",
                    (user_id, prompt, request_id))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"failed saving pending generated image: {e}")
        return 0

    def add_job(self, job_id: str, prompt: str, conversation_id: int | None = None) -> bool:
        """a job was started (status initializing, no result yet). conversation_id may be None"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO jobs (id, status, prompt, conversation_id) VALUES (?, 'initializing', ?, ?)",
                    (job_id, prompt, conversation_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"failed saving job {job_id}: {e}")
        return False

    def set_job(self, job_id: str, status: str, result: dict | None = None) -> bool:
        """running, or done / failed / cancelled (sets finished_at). result: the report {"summary", "details"}, stored as json"""
        finished_at = "CURRENT_TIMESTAMP" if status in ("done", JOB_DONE_WITH_WARNINGS, "failed", "cancelled") else "NULL"
        with self.get_connection() as conn:
            try:
                conn.execute(f"UPDATE jobs SET status = ?, result = ?, finished_at = {finished_at} WHERE id = ?",
                             (status, json.dumps(result) if result is not None else None, job_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"failed setting job {job_id} to {status}: {e}")
        return False

    def fail_stale_jobs(self) -> int:
        """at hub start: jobs still initializing or running lost their thread with the old hub, they are failed. returns how many"""
        result = json.dumps({"error": "interrupted", "details": "hub restarted"})
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE jobs SET status = 'failed', result = ?, finished_at = CURRENT_TIMESTAMP WHERE status IN ('initializing', 'running')",
                                  (result,))
            conn.commit()
            return cursor.rowcount

    def last_user_message_id(self, conversation_id: int) -> int | None:
        """the newest user message of the conversation, None if it has none"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT MAX(id) FROM messages WHERE conversation_id = ? AND role = 'user'", (conversation_id,)).fetchone()
            return row[0] if row else None

    def create_protocol(self, job_id: str, kind: str, user_id: int, name: str, contact_id: int = None, conversation_id: int = None,
                        message_id: int = None, source_id: int = None, time_limit: int = None) -> int:
        """#215 the protocol row of a job or pass that starts (status running), returns its id"""
        with self.get_connection() as conn:
            protocol_id = conn.execute("""INSERT INTO job_protocols (job_id, kind, user_id, name, contact_id, conversation_id, message_id, source_id, time_limit)
                                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                       (job_id, kind, user_id, name or "", contact_id, conversation_id, message_id, source_id,
                                        None if time_limit is None else int(time_limit))).lastrowid
            conn.commit()
            return protocol_id

    @staticmethod
    def _add_protocol_outputs(conn, protocol_id: int, outputs: dict):
        conn.executemany("INSERT INTO protocol_outputs (protocol_id, ref, kind, text) VALUES (?, ?, ?, ?)",
                         [(protocol_id, ref, o["kind"], o["text"]) for ref, o in outputs.items()])

    def add_protocol_line(self, protocol_id: int, seq: int, line: dict, outputs: dict):
        """#215 one line of a running protocol and the long texts it moved to the outputs {ref: {kind, text}}"""
        with self.get_connection() as conn:
            self._add_protocol_outputs(conn, protocol_id, outputs)
            conn.execute("INSERT INTO protocol_lines (protocol_id, seq, at, agent, agent_id, step, task, action, ok, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (protocol_id, seq, line["at"], line["agent"], line["agent_id"], line["step"], line["task"], line["action"], line["ok"],
                          json.dumps(line["data"], ensure_ascii=False, default=str)))
            conn.commit()

    def add_protocol_tool_call(self, protocol_id: int, call: dict):
        with self.get_connection() as conn:
            conn.execute("INSERT INTO protocol_tool_calls (protocol_id, call, at, agent_id, step, task, tool, args, ok, error, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (protocol_id, call["call"], call["at"], call["agent_id"], call["step"], call["task"], call["tool"] or "?", call["args"],
                          call["ok"], call["error"], call["duration_ms"]))
            conn.commit()

    def set_protocol_plan(self, protocol_id: int, plan: dict, outputs: dict):
        """the current plan (its name is the protocol's name too) and the long texts of its new tasks"""
        with self.get_connection() as conn:
            self._add_protocol_outputs(conn, protocol_id, outputs)
            conn.execute("UPDATE job_protocols SET plan = ?, name = COALESCE(?, name) WHERE id = ?",
                         (json.dumps(plan, ensure_ascii=False), plan.get("name") or None, protocol_id))
            conn.commit()

    def finish_protocol(self, protocol_id: int, status: str, name: str = None):
        """the end of a job or pass: done, done_with_warnings, failed or cancelled. prunes the old ones"""
        with self.get_connection() as conn:
            conn.execute("UPDATE job_protocols SET status = ?, name = COALESCE(?, name), finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (status, name or None, protocol_id))
            self._prune_protocols(conn)
            conn.commit()

    def set_protocol_report(self, user_id: int, job_id: str, message_id: int) -> bool:
        """the message that told the user about the job or pass (its conversation too). False: no such protocol of the user"""
        with self.get_connection() as conn:
            count = conn.execute("""UPDATE job_protocols SET report_message_id = ?,
                                    conversation_id = COALESCE((SELECT conversation_id FROM messages WHERE id = ?), conversation_id)
                                    WHERE job_id = ? AND user_id = ?""", (message_id, message_id, job_id, user_id)).rowcount
            conn.commit()
            return count > 0

    def interrupt_protocols(self) -> int:
        """at hub start: the protocols still running lost their job with the old hub. returns how many"""
        with self.get_connection() as conn:
            count = conn.execute("UPDATE job_protocols SET status = 'interrupted', finished_at = CURRENT_TIMESTAMP WHERE status = 'running'").rowcount
            conn.commit()
            return count

    def prune_protocols(self) -> int:
        """deletes the finished protocols older than PROTOCOL_RETENTION_HOURS, returns how many"""
        with self.get_connection() as conn:
            count = self._prune_protocols(conn)
            conn.commit()
            return count

    @staticmethod
    def _prune_protocols(conn) -> int:
        return conn.execute("DELETE FROM job_protocols WHERE status != 'running' AND COALESCE(finished_at, created_at) < datetime('now', ?)",
                            (f"-{PROTOCOL_RETENTION_HOURS} hours",)).rowcount

    _SUMMARY = """SELECT p.job_id, p.kind, p.name, p.status, p.contact_id, c.name AS contact_name, p.conversation_id, p.message_id,
                         p.report_message_id, p.source_id, p.time_limit, p.created_at AS started_at, p.finished_at,
                         (SELECT MAX(seq) FROM protocol_lines l WHERE l.protocol_id = p.id) AS seq
                  FROM job_protocols p LEFT JOIN contacts c ON c.id = p.contact_id"""

    @staticmethod
    def _utc(value):
        """a db timestamp (UTC, 'YYYY-MM-DD HH:MM:SS') as ISO 8601 with Z, None stays None"""
        return f"{value.replace(' ', 'T')}Z" if value and "T" not in value else value

    def _summary(self, row) -> dict:
        return {**dict(row), "started_at": self._utc(row["started_at"]), "finished_at": self._utc(row["finished_at"]), "seq": row["seq"] or 0}

    def protocol_summaries(self, user_id: int) -> list:
        """#215 the user's protocols running or finished in the last PROTOCOL_RETENTION_HOURS (all contacts), newest first: job_id, kind, name, status, contact_id,
        contact_name, conversation_id, message_id, report_message_id, source_id, time_limit, started_at, finished_at (ISO, UTC), seq"""
        with self.get_connection() as conn:
            rows = conn.execute(f"""{self._SUMMARY} WHERE p.user_id = ?
                                    AND (p.status = 'running' OR COALESCE(p.finished_at, p.created_at) >= datetime('now', ?))
                                    ORDER BY p.id DESC""", (user_id, f"-{PROTOCOL_RETENTION_HOURS} hours")).fetchall()
        return [self._summary(row) for row in rows]

    def protocol_summary(self, user_id: int, job_id: str) -> dict | None:
        """one of protocol_summaries, None if the user has no protocol with that job_id"""
        with self.get_connection() as conn:
            row = conn.execute(f"{self._SUMMARY} WHERE p.user_id = ? AND p.job_id = ?", (user_id, job_id)).fetchone()
        return self._summary(row) if row else None

    def contact_name(self, contact_id: int) -> str | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT name FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return row["name"] if row else None

    def protocol_lines(self, user_id: int, job_id: str, after_seq: int = 0):
        """#215 (plan, lines after after_seq [{seq, at, agent, agent_id, step, task, action, ok, data}]) of the user's protocol,
        None if the user has none with that job_id"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT id, plan FROM job_protocols WHERE user_id = ? AND job_id = ?", (user_id, job_id)).fetchone()
            if row is None:
                return None
            lines = conn.execute("SELECT * FROM protocol_lines WHERE protocol_id = ? AND seq > ? ORDER BY seq", (row["id"], after_seq)).fetchall()
        return json.loads(row["plan"]) if row["plan"] else None, [self._line(line) for line in lines]

    @staticmethod
    def _line(line) -> dict:
        return {**{k: line[k] for k in line.keys() if k != "protocol_id"}, "ok": None if line["ok"] is None else bool(line["ok"]),
                "data": json.loads(line["data"])}

    def protocol_output(self, user_id: int, job_id: str, ref: str) -> dict | None:
        """{kind, text} of a long text of the user's protocol, None if there is none"""
        with self.get_connection() as conn:
            row = conn.execute("""SELECT o.kind, o.text FROM protocol_outputs o JOIN job_protocols p ON p.id = o.protocol_id
                                  WHERE p.user_id = ? AND p.job_id = ? AND o.ref = ?""", (user_id, job_id, ref)).fetchone()
        return dict(row) if row else None

    def get_protocols(self, limit: int = 20) -> list:
        """the newest protocols first: id, created_at (UTC), kind, user_id, conversation_id, message_id, job_id, status, name
        (the plan's, else the start of the job's prompt), lines, tool calls and failed tool calls"""
        with self.get_connection() as conn:
            rows = conn.execute("""SELECT p.id, p.created_at, p.kind, p.user_id, p.conversation_id, p.message_id, p.job_id, p.status,
                                          COALESCE(NULLIF(p.name, ''), j.prompt) AS name,
                                          (SELECT COUNT(*) FROM protocol_lines l WHERE l.protocol_id = p.id) AS lines,
                                          (SELECT COUNT(*) FROM protocol_tool_calls c WHERE c.protocol_id = p.id) AS tool_calls,
                                          (SELECT COUNT(*) FROM protocol_tool_calls c WHERE c.protocol_id = p.id AND NOT c.ok) AS failed_calls
                                   FROM job_protocols p LEFT JOIN jobs j ON j.id = p.job_id ORDER BY p.id DESC LIMIT ?""", (limit,)).fetchall()
        return [{**dict(row), "name": " ".join(str(row["name"] or "").split()[:6])} for row in rows]

    def get_protocol(self, protocol_id: int) -> dict | None:
        """one protocol: its row, plan, lines, tool_calls and outputs {ref: {kind, text}}. None if there is none with that id"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM job_protocols WHERE id = ?", (protocol_id,)).fetchone()
            if row is None:
                return None
            lines = conn.execute("SELECT * FROM protocol_lines WHERE protocol_id = ? ORDER BY seq", (protocol_id,)).fetchall()
            calls = conn.execute("SELECT * FROM protocol_tool_calls WHERE protocol_id = ? ORDER BY call", (protocol_id,)).fetchall()
            outputs = conn.execute("SELECT ref, kind, text FROM protocol_outputs WHERE protocol_id = ?", (protocol_id,)).fetchall()
        return {**dict(row), "plan": json.loads(row["plan"]) if row["plan"] else None,
                "lines": [{k: v for k, v in self._line(line).items() if k != "seq"} for line in lines],
                "tool_calls": [{**{k: call[k] for k in call.keys() if k != "protocol_id"}, "ok": bool(call["ok"])} for call in calls],
                "outputs": {o["ref"]: {"kind": o["kind"], "text": o["text"]} for o in outputs}}

    def protocol_tool_stats(self) -> list:
        """per tool over the stored protocols: calls, failed, average and longest duration (ms), the last error. most failures first"""
        with self.get_connection() as conn:
            rows = conn.execute("""SELECT tool, COUNT(*) AS calls, SUM(NOT ok) AS failed, CAST(AVG(duration_ms) AS INTEGER) AS avg_ms,
                                          MAX(duration_ms) AS max_ms,
                                          (SELECT error FROM protocol_tool_calls e WHERE e.tool = c.tool AND NOT e.ok
                                           ORDER BY e.protocol_id DESC, e.call DESC LIMIT 1) AS last_error
                                   FROM protocol_tool_calls c GROUP BY tool ORDER BY failed DESC, calls DESC, tool""").fetchall()
        return [dict(row) for row in rows]

    def complete_generated_image(self, row_id: int, file_name: str) -> bool:
        return self._set_generated_image(row_id, "done", file_name)

    def fail_generated_image(self, row_id: int) -> bool:
        return self._set_generated_image(row_id, "failed", None)

    def _set_generated_image(self, row_id: int, status: str, file_name: str | None) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute("UPDATE generated_images SET status = ?, file_name = ? WHERE id = ?", (status, file_name, row_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"failed setting generated image {row_id} to {status}: {e}")
        return False

    def get_generated_images(self, user_id: int, limit: int = 50) -> list[dict]:
        """the latest rows (pending, done and failed) of this user only, oldest first"""
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    SELECT id, prompt, request_id, file_name, status, created_at FROM (
                        SELECT id, prompt, request_id, file_name, status, created_at FROM generated_images
                        WHERE user_id = ? ORDER BY id DESC LIMIT ?
                    ) ORDER BY id
                """, (user_id, limit)).fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"failed reading generated images of user {user_id}: {e}")
        return []

    def get_user_images(self, user_id: int, limit: int = 60, offset: int = 0) -> list[dict]:
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    WITH all_images AS (
                        SELECT ci.file_key AS file_key, ci.contact_id AS contact_id, NULL AS conversation_id, ci.created_at AS created_at
                        FROM contact_images ci JOIN contacts c ON c.id = ci.contact_id
                        WHERE c.user_id = ?
                        UNION ALL
                        SELECT a.file_name, cv.contact_id, cv.id, m.timestamp
                        FROM attachments a
                        JOIN messages m ON m.id = a.message_id
                        JOIN conversations cv ON cv.id = m.conversation_id
                        WHERE cv.user_id = ? AND a.file_url = 'images/' || a.file_name
                        UNION ALL
                        SELECT file_name, NULL, NULL, created_at FROM generated_images
                        WHERE user_id = ? AND status = 'done' AND file_name IS NOT NULL
                        UNION ALL
                        SELECT profile_image_key, NULL, NULL, NULL FROM user_settings
                        WHERE user_id = ? AND profile_image_key IS NOT NULL AND profile_image_key != ''
                    ), grouped AS (
                        SELECT file_key, MAX(contact_id) AS contact_id, MAX(conversation_id) AS conversation_id, MIN(created_at) AS created_at
                        FROM all_images WHERE file_key IS NOT NULL AND file_key != ''
                        GROUP BY file_key
                    )
                    SELECT g.file_key, g.contact_id, ct.name AS contact_name, g.conversation_id, g.created_at,
                           EXISTS (SELECT 1 FROM images i WHERE i.file_key = g.file_key) AS has_generation
                    FROM grouped g LEFT JOIN contacts ct ON ct.id = g.contact_id
                    ORDER BY g.created_at DESC, g.file_key DESC
                    LIMIT ? OFFSET ?
                """, (user_id, user_id, user_id, user_id, limit, offset)).fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"failed reading images of user {user_id}: {e}")
        return []

    def add_contact_image(self, contact_id: int, file_name: str, image_type: str) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO contact_images (contact_id, type, file_key)
                    VALUES (?, ?, ?)
                """, (contact_id, image_type, file_name))

                conn.commit()
                return cursor.lastrowid

            except Exception as e:
                logger.error(f"Failed adding image for contact {contact_id}: {e}")
        
        return -1

    def get_contact_images(self, contact_id: int, image_type: str = None) -> list[dict]:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                if image_type:
                    cursor.execute("""
                        SELECT id, file_key, type, created_at
                        FROM contact_images
                        WHERE contact_id = ? AND type = ?
                        ORDER BY created_at ASC
                    """, (contact_id, image_type))
                else:
                    cursor.execute("""
                        SELECT id, file_key, type, created_at
                        FROM contact_images
                        WHERE contact_id = ?
                        ORDER BY created_at ASC
                    """, (contact_id,))

                rows = cursor.fetchall()

                images = [
                    {"id": row[0], "file_key": row[1], "type": row[2], "created_at": row[3]}
                    for row in rows
                ]

                return images

            except Exception as e:
                logger.error(f"Failed fetching images for contact {contact_id}: {e}")

        return []

    def get_current_profile_image_key(self, contact_id: int, image_dir: str = "/hub/images") -> str:
        """file key of the contact's current profile image: the newest 'profile' row whose file exists.
        rows are added before their image is generated, so a profile still rendering is skipped and the
        previous one is used. "" if the contact has no finished profile image"""
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    SELECT file_key FROM contact_images
                    WHERE contact_id = ? AND type = 'profile'
                    ORDER BY created_at DESC, id DESC
                """, (contact_id,)).fetchall()
            except Exception as e:
                logger.error(f"Failed fetching profile image of contact {contact_id}: {e}")
                return ""

        for (file_key,) in rows:
            if file_key and "/" not in file_key and (Path(image_dir) / file_key).is_file():
                return file_key
        return ""

    def remove_contact_image(self, image_id: int) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    DELETE FROM contact_images
                    WHERE id = ?
                """, (image_id,))

                conn.commit()
                return cursor.rowcount > 0

            except Exception as e:
                logger.error(f"Failed removing image {image_id}: {e}")
        
        return False

    def update_contact(self, user_id: int, contact_id: int, contact_json: dict):

        if not "identity" in contact_json:
            logger.error(f"missing identity key")
            return False

        if not "profile" in contact_json:
            logger.error(f"missing profile key")
            return False

        identity = contact_json["identity"]
        profile = contact_json["profile"]

        allowed_fields = [
            "name", "gender", "role", "personality"
        ]

        with self.get_connection() as conn:
            updates = []
            values = []

            for key in allowed_fields:
                if key in identity:
                    value = identity[key]

                    updates.append(f"{key} = ?")
                    values.append(value)

            # the companion flag is only set by PUT /contacts/{id}/companion: a saved or imported profile keeps the stored one
            value = json.dumps(profile)
            updates.append("profile = CASE WHEN json_extract(profile, '$.companion') = 1 "
                           "THEN json_set(?, '$.companion', json('true')) ELSE json_remove(?, '$.companion') END")
            values += [value, value]

            # Nothing to update
            if not updates:
                return False

            # Add WHERE clause parameters
            values.append(contact_id)
            values.append(user_id)

            set_clause = ", ".join(updates)

            query = f"""
                UPDATE contacts
                SET {set_clause}
                WHERE id = ? AND user_id = ?
            """

            try:
                cursor = conn.cursor()
                cursor.execute(query, values)
                conn.commit()

                return cursor.rowcount > 0

            except sqlite3.IntegrityError as e:
                logger.error(f"Integrity error: {e}")
                return False

            except Exception as e:
                logger.error(f"updating contact: {e}")
                return False                

    def get_contact_by_id(self, contact_id: int):
        """
        Retrieve contact by contact_id and return as JSON-like dictionary.
        """

        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT *
                    FROM contacts
                    WHERE id = ?
                """, (contact_id,))

                row = cursor.fetchone()

                if not row:
                    return None

                contact = dict(row)

                return {
                    "identity": {
                        "name": contact["name"],
                        "gender": contact["gender"],
                        "role": contact["role"],
                        "personality": contact["personality"]
                    },
                    "profile": json.loads(contact["profile"] or "{}")
                }

            except Exception as e:
                logger.error(f"retrieving contact: {e}")
                return None                
            
    def get_contacts(self, user_id: int):
        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT *
                    FROM contacts
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                """, (user_id,))

                rows = cursor.fetchall()

                contacts = []

                for row in rows:
                    contact = dict(row)

                    # Deserialize JSON fields
                    if contact.get("profile"):
                        profile = json.loads(contact["profile"])
                        contact.pop("profile")
                        contact["profile"] = profile
                    else:
                        continue

                    contacts.append(contact)

                return contacts

            except Exception as e:
                logger.error(f"retrieving contacts: {e}")
                return []        

    def get_conversations(self, user_id: int, contact_id: int):
        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT id, user_id, contact_id, title, context, created_at
                    FROM conversations
                    WHERE user_id = ?
                    AND contact_id = ?
                    ORDER BY created_at DESC
                """, (user_id, contact_id))

                rows = cursor.fetchall()

                conversations = []

                for row in rows:
                    conversation = dict(row)

                    if conversation["context"] != "":
                        try:
                            context = json.loads(conversation["context"])
                        except Exception as e:
                            logger.error(f"failed to load json: {e}")

                        conversation.pop("context")
                        conversation["context"] = context

                    conversations.append(conversation)

                return conversations
            
            except Exception as e:
                logger.error(f"retrieving conversations: {e}")
                
        return []             
            
    def get_conversation(self, conversation_id: int):
        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # summary: the nightly maintenance summary (ConversationSummaryTask), None if there is none yet
                cursor.execute("""
                    SELECT c.id, c.user_id, c.contact_id, c.title, c.context, c.created_at, s.summary
                    FROM conversations c LEFT JOIN conversation_summaries s ON s.conversation_id = c.id
                    WHERE c.id = ?
                """, (conversation_id,))

                row = cursor.fetchone()

                if not row:
                    logger.error(f"can't find conversation with id {conversation_id}")
                    return None                

                # Convert row → dict
                conversation = dict(row)

                if conversation["context"] != "":
                    context = json.loads(conversation["context"])
                    conversation.pop("context")
                    conversation["context"] = context

                return conversation

            except Exception as e:
                logger.error(f"retrieving conversation: {e}")

        return None
    
    def update_conversation(self, conversation_id: int, title: str, context: str) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE conversations
                    SET title = ?, context = ?
                    WHERE id = ?
                """, (title, context, conversation_id))

                conn.commit()

                return cursor.rowcount > 0  # True if a row was updated

            except Exception as e:
                logger.error(f"updating conversation: {e}")

        return False    

    def create_conversation(self, user_id: int, contact_id: int) -> int:
        with self.get_connection() as conn:
            try:
                profile_picture_context = ""
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO conversations (user_id, contact_id, context)
                    VALUES (?, ?, ?)
                """, (user_id, contact_id, profile_picture_context))

                conn.commit()
                return cursor.lastrowid
            
            except Exception as e:
                logger.error(f"failed creating conversation: {e}")
                
        return -1
    
    def delete_conversation(self, conversation_id: int) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    DELETE FROM conversations
                    WHERE id = ?
                """, (conversation_id,))

                conn.commit()

                return cursor.rowcount > 0  # True if something was deleted
            
            except Exception as e:
                logger.error(f"failed deleting conversation: {e}")

        return False

    def conversation_last_activity(self, conversation_id: int) -> str | None:
        """the time of the conversation's latest message (db format, UTC), its creation without messages, None if it is gone"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COALESCE(MAX(m.timestamp), c.created_at)
                    FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                    WHERE c.id = ?
                    GROUP BY c.id
                """, (conversation_id,))
                row = cursor.fetchone()
                return row[0] if row else None
            except Exception as e:
                logger.error(f"failed reading the last activity of conversation {conversation_id}: {e}")
                return ""   # not None: a failed read must not remove its files

    def contact_last_activity(self, contact_id: int) -> str | None:
        """the time of the latest message in any conversation of the contact (db format, UTC), the latest conversation's
        creation without messages, "" without conversations, None if the contact is gone"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("""
                    SELECT ct.id, MAX(COALESCE(m.timestamp, c.created_at))
                    FROM contacts ct
                    LEFT JOIN conversations c ON c.contact_id = ct.id
                    LEFT JOIN messages m ON m.conversation_id = c.id
                    WHERE ct.id = ?
                    GROUP BY ct.id
                """, (contact_id,)).fetchone()
                return (row[1] or "") if row else None
            except Exception as e:
                logger.error(f"failed reading the last activity of contact {contact_id}: {e}")
                return ""   # not None: a failed read must not remove its files

    def get_conversation_image_keys(self, conversation_id: int) -> list[str]:
        """file keys of the hub images attached to messages of this conversation (images/<file_key>)"""
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    SELECT DISTINCT a.file_name
                    FROM attachments a
                    JOIN messages m ON m.id = a.message_id
                    WHERE m.conversation_id = ? AND a.file_url = 'images/' || a.file_name
                """, (conversation_id,)).fetchall()
                return [row[0] for row in rows if row[0]]
            except Exception as e:
                logger.error(f"failed fetching images of conversation {conversation_id}: {e}")
        return []

    def get_contact_image_keys(self, contact_id: int) -> list[str]:
        """file keys of all hub images of this contact: its contact_images (profile, conversation_images)
        and the images attached to messages in any of its conversations"""
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    SELECT file_key FROM contact_images WHERE contact_id = ?
                    UNION
                    SELECT a.file_name
                    FROM attachments a
                    JOIN messages m ON m.id = a.message_id
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.contact_id = ? AND a.file_url = 'images/' || a.file_name
                """, (contact_id, contact_id)).fetchall()
                return [row[0] for row in rows if row[0]]
            except Exception as e:
                logger.error(f"failed fetching images of contact {contact_id}: {e}")
        return []

    def release_images(self, file_keys: list[str], drop_conversation_images: bool = True) -> list[str]:
        """forgets every image in file_keys no message attachment refers to anymore: drops its conversation_images rows,
        and its stored generation if it is no profile image either. returns the file keys whose files can be deleted.
        after delete_contact the contact's own contact_images rows are already gone (cascade), pass
        drop_conversation_images=False so the rows of other contacts are kept and keep their images"""
        unused = []
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                for file_key in set(file_keys):
                    # still attached in another conversation, keep everything
                    if cursor.execute("SELECT 1 FROM attachments WHERE file_name = ? AND file_url = 'images/' || file_name LIMIT 1", (file_key,)).fetchone():
                        continue

                    # conversation_images rows are created by the conversation tools (take_photo, generate_image)
                    if drop_conversation_images:
                        cursor.execute("DELETE FROM contact_images WHERE file_key = ? AND type = 'conversation_images'", (file_key,))

                    # a contact or user profile image keeps its file and generation
                    if cursor.execute("SELECT 1 FROM contact_images WHERE file_key = ? LIMIT 1", (file_key,)).fetchone():
                        continue
                    if cursor.execute("SELECT 1 FROM user_settings WHERE profile_image_key = ? LIMIT 1", (file_key,)).fetchone():
                        continue

                    # an image tool image picked as a contact image stays in the image tool's list
                    if cursor.execute("SELECT 1 FROM generated_images WHERE file_name = ? LIMIT 1", (file_key,)).fetchone():
                        continue

                    cursor.execute("DELETE FROM images WHERE file_key = ?", (file_key,))
                    unused.append(file_key)
                conn.commit()
            except Exception as e:
                logger.error(f"failed releasing images: {e}")
                return []
        return unused

    def owns_contact(self, user_id: int, contact_id: int) -> bool:
        """False for foreign and unknown contacts alike"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT 1 FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id)).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"failed checking contact owner: {e}")
        return False

    def owns_conversation(self, user_id: int, conversation_id: int) -> bool:
        """False for foreign and unknown conversations alike"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT 1 FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"failed checking conversation owner: {e}")
        return False

    def owns_message(self, user_id: int, message_id: int) -> bool:
        """False for foreign and unknown messages alike, a message belongs to the owner of its conversation"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE m.id = ? AND c.user_id = ?", (message_id, user_id)).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"failed checking message owner: {e}")
        return False

    def user_has_image(self, user_id: int, file_key: str) -> bool:
        """True if the image is in the user's gallery (get_user_images): a contact image, a chat attachment,
        an image tool image or the user's current profile image"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("""
                    SELECT 1 FROM contact_images ci JOIN contacts c ON c.id = ci.contact_id WHERE ci.file_key = ? AND c.user_id = ?
                    UNION ALL
                    SELECT 1 FROM attachments a JOIN messages m ON m.id = a.message_id JOIN conversations cv ON cv.id = m.conversation_id
                    WHERE a.file_name = ? AND cv.user_id = ? AND a.file_url = 'images/' || a.file_name
                    UNION ALL
                    SELECT 1 FROM generated_images WHERE file_name = ? AND user_id = ? AND status = 'done'
                    UNION ALL
                    SELECT 1 FROM user_settings WHERE profile_image_key = ? AND user_id = ?
                    LIMIT 1
                """, (file_key, user_id, file_key, user_id, file_key, user_id, file_key, user_id)).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"failed checking image of user: {e}")
        return False

    def owns_image(self, user_id: int, file_key: str) -> bool:
        """False for foreign and unknown images alike: the image belongs to this user as a contact image or their profile image"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("""
                    SELECT 1 FROM contact_images ci JOIN contacts c ON c.id = ci.contact_id WHERE ci.file_key = ? AND c.user_id = ?
                    UNION ALL
                    SELECT 1 FROM user_settings WHERE profile_image_key = ? AND user_id = ?
                    LIMIT 1
                """, (file_key, user_id, file_key, user_id)).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"failed checking image owner: {e}")
        return False

    def delete_contact(self, contact_id: int) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    DELETE FROM contacts
                    WHERE id = ?
                """, (contact_id,))

                conn.commit()

                return cursor.rowcount > 0  # True if something was deleted
            
            except Exception as e:
                logger.error(f"failed deleting contact: {e}")

        return False

    def add_contact_memory(self, user_id: int, contact_id: int, text: str) -> int | None:
        """stores one memory of a contact, returns its id. None if the contact is not the user's:
        the ownership check is part of the insert, a foreign contact_id inserts nothing"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("""
                    INSERT INTO contact_memories (user_id, contact_id, text)
                    SELECT user_id, id, ? FROM contacts WHERE id = ? AND user_id = ?
                """, (text, contact_id, user_id))
                conn.commit()
                return cursor.lastrowid if cursor.rowcount else None
            except Exception as e:
                logger.error(f"failed adding contact memory: {e}")
        return None

    def set_memory_embedding(self, user_id: int, memory_id: int, embedding: list[float]) -> bool:
        """stores or replaces the vector of one of the user's memories in the index.
        False for foreign and unknown memories, a wrong dimension or without sqlite-vec"""
        if len(embedding) != MEMORY_EMBEDDING_DIM:
            logger.error(f"memory embedding not stored (dimension {len(embedding)} of {MEMORY_EMBEDDING_DIM})")
            return False
        with self.get_connection() as conn:
            try:
                # vec0 has no upsert: delete the old vector, insert the new one in the same transaction
                conn.execute("DELETE FROM contact_memory_vectors WHERE memory_id = ? AND user_id = ?", (memory_id, user_id))
                cursor = conn.execute("""
                    INSERT INTO contact_memory_vectors (memory_id, contact_id, user_id, embedding)
                    SELECT m.id, m.contact_id, m.user_id, ? FROM contact_memories m
                    JOIN contacts c ON c.id = m.contact_id
                    WHERE m.id = ? AND m.user_id = ? AND c.user_id = ?
                """, (sqlite_vec.serialize_float32(embedding), memory_id, user_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed storing memory embedding: {e}")
        return False

    def nearest_contact_memories(self, user_id: int, contact_id: int, embedding: list[float], k: int = 5) -> list[dict]:
        """the k memories of this contact closest to embedding, closest first (cosine distance).
        only searches the contact's partition, empty for foreign and unknown contacts alike"""
        if len(embedding) != MEMORY_EMBEDDING_DIM:
            return []
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    WITH knn AS (
                        SELECT memory_id, distance FROM contact_memory_vectors
                        WHERE embedding MATCH ? AND k = ? AND contact_id = ? AND user_id = ?
                    )
                    SELECT m.id, m.text, m.created_at, knn.distance FROM knn
                    JOIN contact_memories m ON m.id = knn.memory_id
                    JOIN contacts c ON c.id = m.contact_id
                    WHERE m.user_id = ? AND c.user_id = ?
                    ORDER BY knn.distance
                """, (sqlite_vec.serialize_float32(embedding), int(k), contact_id, user_id, user_id, user_id)).fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"failed searching memory embeddings: {e}")
        return []

    def get_contact_memories(self, user_id: int, contact_id: int) -> list[dict]:
        """all memories of this contact, newest first, without vectors. empty for foreign and unknown contacts alike"""
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    SELECT m.id, m.text, m.created_at FROM contact_memories m
                    JOIN contacts c ON c.id = m.contact_id
                    WHERE m.contact_id = ? AND m.user_id = ? AND c.user_id = ?
                    ORDER BY m.created_at DESC, m.id DESC
                """, (contact_id, user_id, user_id)).fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"failed reading contact memories: {e}")
        return []

    def delete_contact_memory(self, user_id: int, contact_id: int, memory_id: int) -> bool:
        """deletes one memory of the user's contact, the trigger removes its vector. False for foreign and unknown memories"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("""
                    DELETE FROM contact_memories
                    WHERE id = ? AND contact_id = ? AND user_id = ?
                    AND contact_id IN (SELECT id FROM contacts WHERE user_id = ?)
                """, (memory_id, contact_id, user_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed deleting contact memory: {e}")
        return False

    ########### transcribe app (#198)

    # a segment sent again after a reconnect (the app replays the audio the hub had not answered yet) overlaps the stored one
    SEGMENT_OVERLAP = 0.25

    def create_transcript(self, user_id: int, language: str = "") -> int:
        """a recording was started. returns its id, 0 if it could not be saved"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("INSERT INTO transcripts (user_id, language) VALUES (?, ?)", (user_id, language))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"failed creating a transcript: {e}")
        return 0

    def owns_transcript(self, user_id: int, transcript_id: int) -> bool:
        """False for foreign and unknown transcripts alike"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT 1 FROM transcripts WHERE id = ? AND user_id = ?", (transcript_id, user_id)).fetchone()
                return row is not None
            except Exception as e:
                logger.error(f"failed checking transcript owner: {e}")
        return False

    def get_transcripts(self, user_id: int, limit: int = 100) -> list[dict]:
        """the user's transcripts, newest first, without their text: id, language, duration, created_at, title,
        segments and bookmarks (counts) and preview (the start of the first segment)"""
        with self.get_connection() as conn:
            try:
                rows = conn.execute("""
                    SELECT t.id, t.language, t.duration, t.created_at, t.title,
                        (SELECT COUNT(*) FROM transcript_segments s WHERE s.transcript_id = t.id) AS segments,
                        (SELECT COUNT(*) FROM transcript_bookmarks b WHERE b.transcript_id = t.id) AS bookmarks,
                        COALESCE((SELECT substr(s.text, 1, 100) FROM transcript_segments s WHERE s.transcript_id = t.id
                                  ORDER BY s.start_time LIMIT 1), '') AS preview
                    FROM transcripts t WHERE t.user_id = ? ORDER BY t.id DESC LIMIT ?
                """, (user_id, limit)).fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"failed reading transcripts of user {user_id}: {e}")
        return []

    def get_transcript(self, transcript_id: int) -> dict | None:
        """one transcript with its segments [{id, start, end, text, edited, kind}] and bookmarks [{id, at, label}], both in time order"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT id, language, duration, created_at, title FROM transcripts WHERE id = ?", (transcript_id,)).fetchone()
                if row is None:
                    return None
                segments = conn.execute("""SELECT id, start_time AS start, end_time AS end, text, edited, kind FROM transcript_segments
                                           WHERE transcript_id = ? ORDER BY start_time, id""", (transcript_id,)).fetchall()
                bookmarks = conn.execute("""SELECT id, at_time AS at, label FROM transcript_bookmarks
                                            WHERE transcript_id = ? ORDER BY at_time, id""", (transcript_id,)).fetchall()
                return {**dict(row), "segments": [dict(s) for s in segments], "bookmarks": [dict(b) for b in bookmarks]}
            except Exception as e:
                logger.error(f"failed reading transcript {transcript_id}: {e}")
        return None

    def add_transcript_segment(self, transcript_id: int, start: float, end: float, text: str) -> int:
        """the text of one utterance, start / end in seconds of the recording. returns the row id,
        0 if it overlaps a stored segment by more than SEGMENT_OVERLAP (the same audio again) or could not be saved"""
        with self.get_connection() as conn:
            try:
                if conn.execute("""SELECT 1 FROM transcript_segments WHERE transcript_id = ?
                                   AND end_time > ? + ? AND start_time < ? - ? LIMIT 1""",
                                (transcript_id, start, self.SEGMENT_OVERLAP, end, self.SEGMENT_OVERLAP)).fetchone():
                    return 0
                cursor = conn.execute("INSERT INTO transcript_segments (transcript_id, start_time, end_time, text) VALUES (?, ?, ?, ?)",
                                      (transcript_id, start, end, text))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"failed adding a segment to transcript {transcript_id}: {e}")
        return 0

    def add_transcript_heading(self, transcript_id: int, at: float, text: str) -> int:
        """a heading the user added at second at (between two segments, no overlap check), returns its id or 0"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("""INSERT INTO transcript_segments (transcript_id, start_time, end_time, text, kind)
                                         VALUES (?, ?, ?, ?, 'heading')""", (transcript_id, at, at, text))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"failed adding a heading to transcript {transcript_id}: {e}")
        return 0

    def split_transcript_segment(self, transcript_id: int, segment_id: int, parts: list[dict]) -> list[int]:
        """the segment becomes parts [{start, end, text, kind}] in one go (a marked text made a heading): the first
        keeps its row, the others are new rows. each part's text is its text from now on (edited cleared), its times
        inside the segment's. returns the ids in order, [] if the segment is not there, a time is outside or it failed"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT start_time, end_time FROM transcript_segments WHERE id = ? AND transcript_id = ?",
                                   (segment_id, transcript_id)).fetchone()
                if row is None or not parts:
                    return []
                low, high = min(row[0], row[1]) - 1e-6, max(row[0], row[1]) + 1e-6
                if any(not (low <= p["start"] <= high and low <= p["end"] <= high) for p in parts):
                    return []
                first, rest = parts[0], parts[1:]
                conn.execute("""UPDATE transcript_segments SET start_time = ?, end_time = ?, text = ?, edited = NULL, kind = ?
                                WHERE id = ?""", (first["start"], first["end"], first["text"], first["kind"], segment_id))
                ids = [segment_id]
                for p in rest:
                    cursor = conn.execute("""INSERT INTO transcript_segments (transcript_id, start_time, end_time, text, kind)
                                             VALUES (?, ?, ?, ?, ?)""", (transcript_id, p["start"], p["end"], p["text"], p["kind"]))
                    ids.append(cursor.lastrowid)
                conn.commit()
                return ids
            except Exception as e:
                conn.rollback()
                logger.error(f"failed splitting segment {segment_id}: {e}")
        return []

    def edit_transcript_segment(self, transcript_id: int, segment_id: int, text: str | None) -> bool:
        """the user's text for a segment (None: back to the recognised one), the recognised text stays"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("UPDATE transcript_segments SET edited = ? WHERE id = ? AND transcript_id = ?",
                                      (text, segment_id, transcript_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed editing segment {segment_id}: {e}")
        return False

    def set_transcript_duration(self, transcript_id: int, duration: float) -> bool:
        """the seconds recorded so far, a shorter value (a replay after a reconnect) keeps the longer one"""
        with self.get_connection() as conn:
            try:
                conn.execute("UPDATE transcripts SET duration = MAX(duration, ?) WHERE id = ?", (duration, transcript_id))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"failed setting the duration of transcript {transcript_id}: {e}")
        return False

    def add_transcript_bookmark(self, transcript_id: int, at: float, label: str = "") -> int:
        """a bookmark at second at of the recording, returns its id (0 if it could not be saved)"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("INSERT INTO transcript_bookmarks (transcript_id, at_time, label) VALUES (?, ?, ?)",
                                      (transcript_id, at, label))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"failed adding a bookmark to transcript {transcript_id}: {e}")
        return 0

    def rename_transcript_bookmark(self, transcript_id: int, bookmark_id: int, label: str) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("UPDATE transcript_bookmarks SET label = ? WHERE id = ? AND transcript_id = ?",
                                      (label, bookmark_id, transcript_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed renaming bookmark {bookmark_id}: {e}")
        return False

    def delete_transcript_bookmark(self, transcript_id: int, bookmark_id: int) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("DELETE FROM transcript_bookmarks WHERE id = ? AND transcript_id = ?", (bookmark_id, transcript_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed deleting bookmark {bookmark_id}: {e}")
        return False

    def copy_transcript(self, user_id: int, transcript: dict, title: str, texts: dict[int, str]) -> int:
        """a new transcript of the user, a copy of transcript (get_transcript) named title: the same segments (times,
        kinds, edits) and bookmarks, the segments in texts (id -> text) with that text instead (their edit cleared).
        all or nothing, returns the copy's id or 0"""
        with self.get_connection() as conn:
            try:
                copy_id = conn.execute("INSERT INTO transcripts (user_id, language, duration, title) VALUES (?, ?, ?, ?)",
                                       (user_id, transcript.get("language", ""), transcript.get("duration", 0.0), title)).lastrowid
                for s in transcript.get("segments", []):
                    text, edited = (texts[s["id"]], None) if s["id"] in texts else (s["text"], s.get("edited"))
                    conn.execute("""INSERT INTO transcript_segments (transcript_id, start_time, end_time, text, edited, kind)
                                    VALUES (?, ?, ?, ?, ?, ?)""", (copy_id, s["start"], s["end"], text, edited, s.get("kind") or ""))
                for b in transcript.get("bookmarks", []):
                    conn.execute("INSERT INTO transcript_bookmarks (transcript_id, at_time, label) VALUES (?, ?, ?)",
                                 (copy_id, b["at"], b.get("label", "")))
                conn.commit()
                return copy_id
            except Exception as e:
                conn.rollback()
                logger.error(f"failed copying transcript {transcript.get('id')}: {e}")
        return 0

    def delete_empty_transcripts(self, user_id: int, min_age_seconds: int, keep=()) -> int:
        """deletes the user's transcripts without text, bookmarks and title (a recording that got nothing) made more than
        min_age_seconds ago, except the ids in keep (being recorded). returns how many"""
        keep = [int(transcript_id) for transcript_id in keep]
        with self.get_connection() as conn:
            try:
                cursor = conn.execute(f"""
                    DELETE FROM transcripts WHERE user_id = ? AND title = ''
                        AND created_at < datetime('now', ?)
                        AND NOT EXISTS (SELECT 1 FROM transcript_segments s WHERE s.transcript_id = transcripts.id)
                        AND NOT EXISTS (SELECT 1 FROM transcript_bookmarks b WHERE b.transcript_id = transcripts.id)
                        AND id NOT IN ({",".join("?" * len(keep))})
                """, (user_id, f"-{int(min_age_seconds)} seconds", *keep))
                conn.commit()
                if cursor.rowcount:
                    logger.info(f"deleted {cursor.rowcount} empty transcripts of user {user_id}")
                return cursor.rowcount
            except Exception as e:
                logger.error(f"failed deleting the empty transcripts of user {user_id}: {e}")
        return 0

    def delete_transcript(self, user_id: int, transcript_id: int) -> bool:
        """the transcript with its segments and bookmarks. False for foreign and unknown transcripts"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("DELETE FROM transcripts WHERE id = ? AND user_id = ?", (transcript_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed deleting transcript {transcript_id}: {e}")
        return False

    ########### conversation summaries (#147, app/maintenance)

    # conversations with messages, their last message time and whether they have a summary / a vector
    _SUMMARY_STATE = """
        SELECT c.id, c.user_id, c.contact_id, s.summary, s.updated_at,
            (SELECT MAX(m.timestamp) FROM messages m WHERE m.conversation_id = c.id) AS last_message,
            EXISTS (SELECT 1 FROM conversation_summary_vectors v WHERE v.conversation_id = c.id) AS has_vector
        FROM conversations c LEFT JOIN conversation_summaries s ON s.conversation_id = c.id
    """

    def conversations_to_summarize(self, user_id: int | None = None, limit: int | None = None) -> list[dict]:
        """conversations without a summary, with messages newer than their summary or without a vector, oldest change first.
        stale = the summary has to be made (again), else only the vector is missing. user_id None = all users"""
        with self.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT *, (summary IS NULL OR last_message > updated_at) AS stale FROM ({self._SUMMARY_STATE})
                WHERE last_message IS NOT NULL AND (? IS NULL OR user_id = ?)
                AND (summary IS NULL OR last_message > updated_at OR NOT has_vector)
                ORDER BY last_message LIMIT ?
            """, (user_id, user_id, -1 if limit is None else int(limit))).fetchall()
            return [dict(row) for row in rows]

    def summary_status(self) -> dict:
        """hub management: how many conversations (with messages) are summarized, stale or without a vector"""
        with self.get_connection() as conn:
            row = conn.execute(f"""
                SELECT COUNT(*) AS conversations, COUNT(summary) AS summarized,
                    SUM(summary IS NULL) AS missing, SUM(summary IS NOT NULL AND last_message > updated_at) AS stale,
                    SUM(summary IS NOT NULL AND NOT has_vector) AS without_vector, MAX(updated_at) AS last_update
                FROM ({self._SUMMARY_STATE}) WHERE last_message IS NOT NULL
            """).fetchone()
            return {k: row[k] or 0 for k in row.keys()} | {"last_update": row["last_update"]}

    def set_conversation_summary(self, conversation_id: int, summary: str, updated_at: str) -> bool:
        """stores or replaces the summary. the old vector goes with it, set_conversation_embedding adds the new one"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM conversation_summary_vectors WHERE conversation_id = ?", (conversation_id,))
            cursor = conn.execute("""
                INSERT INTO conversation_summaries (conversation_id, summary, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at
            """, (conversation_id, summary, updated_at))
            conn.commit()
            return cursor.rowcount == 1

    def set_conversation_embedding(self, conversation_id: int, embedding: list[float]) -> bool:
        """stores or replaces the vector of a conversation's summary. False for unknown conversations or a wrong dimension"""
        if len(embedding) != MEMORY_EMBEDDING_DIM:
            logger.error(f"summary embedding not stored (dimension {len(embedding)} of {MEMORY_EMBEDDING_DIM})")
            return False
        with self.get_connection() as conn:
            try:
                # vec0 has no upsert, like set_memory_embedding
                conn.execute("DELETE FROM conversation_summary_vectors WHERE conversation_id = ?", (conversation_id,))
                cursor = conn.execute("""
                    INSERT INTO conversation_summary_vectors (conversation_id, user_id, contact_id, embedding)
                    SELECT id, user_id, contact_id, ? FROM conversations WHERE id = ?
                """, (sqlite_vec.serialize_float32(embedding), conversation_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"failed storing summary embedding: {e}")
        return False

    def nearest_conversations(self, user_id: int, embedding: list[float], k: int = 5, contact_id: int | None = None,
                              exclude_id: int | None = None) -> list[dict]:
        """the k conversations of the user whose summaries are closest to embedding, closest first (cosine distance),
        optionally only those with one contact and without one conversation (e.g. the current one)"""
        if len(embedding) != MEMORY_EMBEDDING_DIM:
            return []
        contact_filter = "AND contact_id = ?" if contact_id is not None else ""
        with self.get_connection() as conn:
            try:
                rows = conn.execute(f"""
                    WITH knn AS (
                        SELECT conversation_id, distance FROM conversation_summary_vectors
                        WHERE embedding MATCH ? AND k = ? AND user_id = ? {contact_filter}
                    )
                    SELECT c.id, c.contact_id, ct.name AS contact, c.title, c.created_at, s.summary, s.updated_at, knn.distance
                    FROM knn JOIN conversations c ON c.id = knn.conversation_id
                    JOIN conversation_summaries s ON s.conversation_id = c.id
                    JOIN contacts ct ON ct.id = c.contact_id
                    WHERE c.user_id = ? AND c.id IS NOT ?
                    ORDER BY knn.distance LIMIT ?
                """, (sqlite_vec.serialize_float32(embedding), int(k) + 1, user_id,
                      *([contact_id] if contact_id is not None else []), user_id, exclude_id, int(k))).fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"failed searching conversation summaries: {e}")
        return []

    def get_message_count_by_conversation(self, conversation_id: int):
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM messages WHERE conversation_id = ?
                """, (conversation_id,))
                return cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"failed returning message count: {e}")
                return 0

    def get_messages_by_conversation(self, conversation_id: int, max_messages: int):
        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
            
                cursor.execute("""
                    SELECT *
                    FROM (
                        SELECT id, role, name, content, timestamp, sources, data
                        FROM messages
                        WHERE conversation_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                    ORDER BY timestamp ASC;
                """, (conversation_id, max_messages))

                messages = [dict(row) for row in cursor.fetchall()]
                for message in messages:
                    message["sources"] = json.loads(message["sources"]) if message["sources"] else []
                    message["data"] = json.loads(message["data"]) if message["data"] else {}
                return messages
            except Exception as e:
                logger.error(f"failed returning messages: {e}")         

    def add_message(self, conversation_id: int, role: str, content: str, name: str) -> int:
        valid_roles = {"user", "assistant", "system", "error"}

        if role not in valid_roles:
            logger.error(f"Invalid role: {role}")
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO messages (conversation_id, role, name, content)
                VALUES (?, ?, ?, ?)
            """, (conversation_id, role, name, content))

            return cursor.lastrowid    
        
    def update_message(self, message_id: int, role: str, content: str, name: str) -> bool:
        valid_roles = {"user", "assistant", "system", "error"}

        if role not in valid_roles:
            logger.error(f"Invalid role: {role}")
            return None

        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE messages 
                    SET role = ?, name = ?, content = ?
                    WHERE id = ?
                """, (role, name, content, message_id))

                conn.commit()

                return cursor.rowcount > 0  # True if a row was updated       

            except Exception as e:
                logger.error(f"updating message: {e}")

        return False

    def append_to_message(self, message_id: int, content: str) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE messages 
                    SET content = COALESCE(content, '') || ?
                    WHERE id = ?
                """, (content, message_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"appending to message: {e}")
        return False

    def delete_message(self, message_id: int) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"deleting message: {e}")
        return False

    def set_message_sources(self, message_id: int, sources: list) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("UPDATE messages SET sources = ? WHERE id = ?", (json.dumps(sources), message_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"setting message sources: {e}")
        return False

    def set_message_data(self, message_id: int, kind: str, value) -> bool:
        """stores value under kind in the data of message_id ({kind: value}, the other kinds stay). a tool's poll, map or price
        ranking: a new kind needs no schema change, the client shows the kinds it knows (Tool.show_data)"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                self._set_message_data(cursor, message_id, kind, value)
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"setting message data {kind}: {e}")
        return False

    @staticmethod
    def _set_message_data(cursor, message_id: int, kind: str, value) -> None:
        """merges {kind: value} into the data of message_id in one statement, a parallel call for another kind is kept"""
        if not kind.isidentifier():
            raise ValueError(f"not a kind of message data: {kind}")
        cursor.execute("UPDATE messages SET data = json_set(COALESCE(data, '{}'), ?, json(?)) WHERE id = ?",
                       (f"$.{kind}", json.dumps(value), message_id))

    @staticmethod
    def _message_data(cursor, message_id: int, conversation_id: int) -> dict:
        """the data of message_id in conversation_id, {} if it has none or is not there"""
        row = cursor.execute("SELECT data FROM messages WHERE id = ? AND conversation_id = ?", (message_id, conversation_id)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    def answer_poll(self, message_id: int, conversation_id: int, chosen: list) -> list | None:
        """stores the user's choice in the open poll of message_id (in conversation_id). the valid choices in option order,
        None if there is no open poll or no valid choice (single mode: exactly one)"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                poll = self._message_data(cursor, message_id, conversation_id).get("poll")
                if not isinstance(poll, dict) or poll.get("chosen"):
                    return None
                chosen = [option for option in poll["options"] if option in chosen]
                if not chosen or (poll["mode"] == "single" and len(chosen) != 1):
                    return None
                poll["chosen"] = chosen
                self._set_message_data(cursor, message_id, "poll", poll)
                conn.commit()
                return chosen
            except Exception as e:
                logger.error(f"answering poll: {e}")
        return None

    def add_message_file(self, user_id: int, conversation_id: int, message_id: int, real_name: str,
                         stored_name: str, file_type: str, file_size: int, parent_id: int = None) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO message_files
                    (user_id, conversation_id, message_id, real_name, stored_name, file_type, file_size, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, conversation_id, message_id, real_name, stored_name, file_type, file_size, parent_id))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"failed adding message file {real_name} for message {message_id}: {e}")
        return -1

    def get_message_file(self, message_id: int, stored_name: str) -> dict | None:
        """the downloadable row with this hashed name"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("""
                    SELECT id, user_id, conversation_id, message_id, real_name, stored_name, file_type, file_size, parent_id
                    FROM message_files
                    WHERE message_id = ? AND stored_name = ? AND parent_id IS NULL
                """, (message_id, stored_name)).fetchone()
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"failed reading message file {stored_name}: {e}")
        return None

    def get_message_files_for_messages(self, message_ids: list[int]) -> dict[int, list]:
        if not message_ids:
            return {}
        marks = ",".join("?" for _ in message_ids)
        with self.get_connection() as conn:
            try:
                rows = conn.execute(f"""
                    SELECT id, user_id, conversation_id, message_id, real_name, stored_name, file_type, file_size, parent_id
                    FROM message_files WHERE message_id IN ({marks}) ORDER BY id
                """, message_ids).fetchall()
                grouped = {}
                for row in rows:
                    grouped.setdefault(row["message_id"], []).append(dict(row))
                return grouped
            except Exception as e:
                logger.error(f"failed reading message files: {e}")
        return {}

    def add_attachment(self, message_id: int, file_name: str, file_url: str, file_type: str, file_size: int) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO attachments (message_id, file_name, file_url, file_type, file_size)
                    VALUES (?, ?, ?, ?, ?)
                """, (message_id, file_name, file_url, file_type, file_size))

                conn.commit()
                return cursor.lastrowid

            except Exception as e:
                logger.error(f"Failed adding attachment for message {message_id}: {e}")
        
        return -1
    
    def set_attachment_size(self, file_url: str, file_size: int) -> int:
        """the size of the attachments of file_url, for images attached before they exist (ImageTool). returns how many"""
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("UPDATE attachments SET file_size = ? WHERE file_url = ?", (file_size, file_url))
                conn.commit()
                return cursor.rowcount
            except Exception as e:
                logger.error(f"failed setting the size of {file_url}: {e}")
        return 0

    def get_attachments_for_message(self, message_id: int) -> list:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT id, file_name, file_url, file_type, file_size
                    FROM attachments
                    WHERE message_id = ?
                """, (message_id,))

                rows = cursor.fetchall()

                return [
                    {
                        "id": row[0],
                        "file_name": row[1],
                        "file_url": row[2],
                        "file_type": row[3],
                        "file_size": row[4],
                    }
                    for row in rows
                ]

            except Exception as e:
                logger.error(f"Failed fetching attachments for message {message_id}: {e}")
        
        return []    

    def get_attachments_for_messages(self, message_ids: list[int]) -> dict[int, list]:
        """attachments of many messages in one query: message id -> list shaped like get_attachments_for_message"""
        if not message_ids:
            return {}
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(message_ids))
                cursor.execute(f"""
                    SELECT message_id, id, file_name, file_url, file_type, file_size
                    FROM attachments
                    WHERE message_id IN ({placeholders})
                    ORDER BY id
                """, message_ids)

                attachments = {}
                for row in cursor.fetchall():
                    attachments.setdefault(row[0], []).append({
                        "id": row[1],
                        "file_name": row[2],
                        "file_url": row[3],
                        "file_type": row[4],
                        "file_size": row[5],
                    })
                return attachments

            except Exception as e:
                logger.error(f"Failed fetching attachments for messages: {e}")

        return {}

    # ---- voices ---------------------------------------------------------
    # the wav file lives in VOICES_DIR/<file_key>, the row only knows the file key

    VOICES_DIR = Path("/hub/voices")

    def add_voice(self, user_id: int, sample_rate: int, duration: float, contact_id: int | None = None, file_key: str | None = None, content_hash: str | None = None, predefined_id: str = "") -> str | None:
        """inserts a voice row and returns its uuid, or None on failure. file_key defaults to <uuid>.wav"""
        voice_id = str(uuid.uuid4())
        file_key = file_key or f"{voice_id}.wav"
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO voices (id, user_id, contact_id, file_key, sample_rate, duration, content_hash, predefined_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (voice_id, user_id, contact_id, file_key, sample_rate, duration, content_hash, predefined_id))
                conn.commit()
                return voice_id

            except Exception as e:
                logger.error(f"failed adding voice for user {user_id}: {e}")

        return None

    def find_voice_by_hash(self, user_id: int, content_hash: str, predefined_id: str = "") -> str | None:
        """returns the id of a voice of this user with the same sha256 and the same origin, or None.
        an upload ("") never reuses a predefined voice row and the other way round, even if the bytes are equal"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM voices WHERE user_id = ? AND content_hash = ? AND predefined_id = ? LIMIT 1",
                    (user_id, content_hash, predefined_id),
                )
                row = cursor.fetchone()
                return row["id"] if row else None
            except Exception as e:
                logger.error(f"failed looking up voice hash for user {user_id}: {e}")
        return None

    def find_user_voice(self, user_id: int, value: str) -> str | None:
        """id of this user's voice whose id or sha256 content hash is value, or None. an exact id wins"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM voices WHERE user_id = ? AND (id = ? OR content_hash = ?) ORDER BY id = ? DESC LIMIT 1",
                    (user_id, value, value, value),
                )
                row = cursor.fetchone()
                return row["id"] if row else None
            except Exception as e:
                logger.error(f"failed looking up voice {value} for user {user_id}: {e}")
        return None

    def find_predefined_voice(self, user_id: int, predefined_id: str) -> str | None:
        """id of the user's stored copy of a predefined voice, or None"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM voices WHERE user_id = ? AND predefined_id = ? LIMIT 1
                """, (user_id, predefined_id))
                row = cursor.fetchone()
                return row["id"] if row else None
            except Exception as e:
                logger.error(f"failed looking up predefined voice {predefined_id} for user {user_id}: {e}")
        return None

    def remove_voice(self, voice_id: str, user_id: int | None = None) -> bool:
        """deletes the voice row and its wav file. with user_id only a voice owned by that user is removed"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                if user_id is None:
                    cursor.execute("SELECT file_key FROM voices WHERE id = ?", (voice_id,))
                else:
                    cursor.execute("SELECT file_key FROM voices WHERE id = ? AND user_id = ?", (voice_id, user_id))
                row = cursor.fetchone()
                if not row:
                    logger.warning(f"voice {voice_id} not found")
                    return False

                cursor.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
                conn.commit()

            except Exception as e:
                logger.error(f"failed removing voice {voice_id}: {e}")
                return False

        # file is removed after the row, a leftover file is harmless, a row without file is not
        try:
            (self.VOICES_DIR / row["file_key"]).unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"failed deleting voice file {row['file_key']}: {e}")

        return True


    ########### invites
    @staticmethod
    def _now() -> str:
        # one fixed format so expiry strings compare correctly as text
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_invite(self, created_by: str | None = None, email: str | None = None, expires_in_days: float | None = 7, max_uses: int = 1, nsfw_allowed: bool = False) -> str:
        """
        Creates an invite and returns the plain token. Only its hash is stored.
        nsfw_allowed: the invited user may use NSFW settings (default off = SFW only)
        """
        token = secrets.token_urlsafe(24)
        expires_at = None
        if expires_in_days is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat(timespec="seconds")

        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO invites (token_hash, created_by, email, expires_at, max_uses, nsfw_allowed) VALUES (?, ?, ?, ?, ?, ?)",
                (self._hash_token(token), created_by, email.lower() if email else None, expires_at, max_uses, 1 if nsfw_allowed else 0)
            )
        logger.info(f"invite created by {created_by or 'no name'}")
        return token

    def get_invites(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, created_by, email, expires_at, max_uses, uses, used_at, used_by, nsfw_allowed, created_at FROM invites ORDER BY id"
            )
            return [dict(row) for row in cursor.fetchall()]

    def remove_invite(self, invite_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM invites WHERE id = ?", (invite_id,))
            return cursor.rowcount > 0

    # hub management: change the NSFW permission after creation
    def set_invite_nsfw(self, invite_id: int, nsfw_allowed: bool) -> bool:
        """only affects users who sign up with this invite from now on. False if the invite doesn't exist."""
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE invites SET nsfw_allowed = ? WHERE id = ?", (1 if nsfw_allowed else 0, invite_id))
            return cursor.rowcount > 0

    def set_user_nsfw(self, username: str, nsfw_allowed: bool) -> bool:
        """the user sees the change on their next login. False if the user doesn't exist."""
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE users SET nsfw_allowed = ? WHERE username = ?", (1 if nsfw_allowed else 0, username))
            return cursor.rowcount > 0

    def get_users_admin(self) -> list:
        """users with their NSFW permission, for the hub management tool only (not exposed over HTTP)"""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT id, username, nsfw_allowed, created_at FROM users ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

    def hub_stats(self, active_minutes: int = 10) -> dict:
        """counts for the hub management tool: running agent jobs, users, users active in the last active_minutes.
        active = wrote a message, logged in or refreshed their login in that time (an open app that only reads is not seen)"""
        since = datetime.now(timezone.utc) - timedelta(minutes=active_minutes)
        since_message = since.strftime("%Y-%m-%d %H:%M:%S")       # messages.timestamp: CURRENT_TIMESTAMP format
        since_token = since.isoformat(timespec="seconds")          # refresh_tokens: isoformat with +00:00
        with self.get_connection() as conn:
            agents = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('initializing', 'running')").fetchone()[0]
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active = conn.execute("""
                SELECT COUNT(*) FROM users u WHERE EXISTS (
                    SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = u.id AND m.role = 'user' AND m.timestamp >= ?
                ) OR EXISTS (
                    SELECT 1 FROM refresh_tokens t WHERE t.user_id = u.id AND (t.created_at >= ? OR t.last_used_at >= ?)
                )""", (since_message, since_token, since_token)).fetchone()[0]
        return {"running_agent_jobs": agents, "users": users, f"active_last_{active_minutes}min": active}

    def create_user_with_invite(self, username: str, passwd: str, token: str, email: str | None = None) -> tuple[int | None, str | None]:
        """
        Redeems an invite and creates the user in one transaction.
        Returns (user_id, None) on success or (None, reason) on failure.
        If the user can't be created the invite use is rolled back.
        """
        now = self._now()
        conn = self.get_connection()
        try:
            # take the write lock up front so two signups can't redeem the last use at once
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, email, expires_at, max_uses, uses, nsfw_allowed FROM invites WHERE token_hash = ?",
                (self._hash_token(token),)
            ).fetchone()

            if row is None:
                reason = "unknown"
            elif row["expires_at"] is not None and row["expires_at"] <= now:
                reason = "expired"
            elif row["uses"] >= row["max_uses"]:
                reason = "exhausted"
            elif row["email"] is not None and (email or "").lower() != row["email"]:
                reason = "email mismatch"
            else:
                reason = None

            if reason:
                conn.rollback()
                return None, reason

            try:
                # the user gets the invite's NSFW permission (0 = SFW only)
                cursor = conn.execute(
                    "INSERT INTO users (username, password, nsfw_allowed) VALUES (?, ?, ?)",
                    (username, passwd, 1 if row["nsfw_allowed"] else 0)
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return None, "username exists"

            user_id = cursor.lastrowid
            conn.execute(
                "UPDATE invites SET uses = uses + 1, used_at = ?, used_by = ? WHERE id = ?",
                (now, user_id, row["id"])
            )
            conn.commit()
            logger.info(f"created user via invite {row['id']}")
            return user_id, None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    ########### user settings

    def get_user_timezone(self, user_id: int) -> str | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT timezone FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return row["timezone"] if row and row["timezone"] else None

    def get_device_timezone(self, user_id: int) -> str | None:
        """the timezone of the device the user logged in with last (set_device_timezone), None if none sent one"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT device_timezone FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return row["device_timezone"] if row and row["device_timezone"] else None

    def set_device_timezone(self, user_id: int, timezone: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO user_settings (user_id, device_timezone) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET device_timezone = excluded.device_timezone
            """, (user_id, timezone))
            conn.commit()
            return cursor.rowcount == 1

    def set_user_timezone(self, user_id: int, timezone: str | None) -> bool:
        """the timezone the user chose, None clears it (their device's counts again, get_device_timezone)"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO user_settings (user_id, timezone) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
            """, (user_id, timezone))
            conn.commit()
            return cursor.rowcount == 1

    def get_user_tts_voice(self, user_id: int) -> str | None:
        """the voice uuid the user chose for the text_to_speech tool, None: the contact's voice"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT tts_voice FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return row["tts_voice"] if row and row["tts_voice"] else None

    def set_user_tts_voice(self, user_id: int, voice: str | None) -> bool:
        """voice: one of the user's voice uuids (the caller checks), None: back to the contact's voice"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO user_settings (user_id, tts_voice) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET tts_voice = excluded.tts_voice
            """, (user_id, voice or None))
            conn.commit()
            return cursor.rowcount == 1

    def get_user_profile_image_key(self, user_id: int) -> str | None:
        """the current profile image file key, None if the user has none"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT profile_image_key FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return row["profile_image_key"] if row and row["profile_image_key"] else None

    def get_current_user_profile_image_key(self, user_id: int, image_dir: str = "/hub/images") -> str:
        """file key of the user's current profile image if the file exists, otherwise "".
        same existence check as get_current_profile_image_key: a lost upload or a key not on disk is skipped,
        so image generation can run without a face reference"""
        file_key = self.get_user_profile_image_key(user_id)
        if file_key and "/" not in file_key and (Path(image_dir) / file_key).is_file():
            return file_key
        return ""

    def set_user_profile_image_key(self, user_id: int, file_key: str | None) -> str | None:
        """sets the current profile image (None clears it). returns the previous key, if any"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT profile_image_key FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            previous = row["profile_image_key"] if row and row["profile_image_key"] else None
            conn.execute("""
                INSERT INTO user_settings (user_id, profile_image_key) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET profile_image_key = excluded.profile_image_key
            """, (user_id, file_key))
            conn.commit()
            return previous

    ########### companion calendar

    # only rows of contacts that are still companions fire
    _COMPANION = "json_extract(c.profile, '$.companion') = 1"
    TASK_KIND = "task"     # #170 the rows of the user's tasks, the others are the companion's own life

    def set_contact_companion(self, user_id: int, contact_id: int, enabled: bool) -> bool:
        """the companion flag lives in the profile. switching it off drops the calendar, on again seeds a new one"""
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE contacts SET profile = json_set(profile, '$.companion', json(?)) WHERE id = ? AND user_id = ?",
                                  ("true" if enabled else "false", contact_id, user_id))
            if cursor.rowcount == 1 and not enabled:
                conn.execute("DELETE FROM companion_calendar WHERE contact_id = ?", (contact_id,))
            conn.commit()
            return cursor.rowcount == 1

    def is_companion(self, contact_id: int) -> bool:
        with self.get_connection() as conn:
            return conn.execute(f"SELECT 1 FROM contacts c WHERE c.id = ? AND {self._COMPANION}", (contact_id,)).fetchone() is not None

    def drop_inactive_companion_rows(self) -> int:
        """the calendars of contacts that are no companions (anymore), e.g. the flag was edited in the db"""
        with self.get_connection() as conn:
            cursor = conn.execute(f"""
                DELETE FROM companion_calendar WHERE contact_id NOT IN (SELECT c.id FROM contacts c WHERE {self._COMPANION})
            """)
            conn.commit()
            return cursor.rowcount

    def last_companion_run(self, contact_id: int) -> str | None:
        """when the companion's last pass ran (missed rows don't count)"""
        with self.get_connection() as conn:
            return conn.execute("SELECT MAX(fired_at) FROM companion_calendar WHERE contact_id = ?", (contact_id,)).fetchone()[0]

    def unseeded_companions(self) -> list[dict]:
        """companions without a calendar yet (the user's tasks don't count): id, user_id"""
        with self.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT c.id, c.user_id FROM contacts c
                WHERE {self._COMPANION} AND NOT EXISTS (SELECT 1 FROM companion_calendar r WHERE r.contact_id = c.id AND r.kind != ?)
            """, (self.TASK_KIND,)).fetchall()
            return [dict(row) for row in rows]

    def add_companion_row(self, contact_id: int, due_at: str, kind: str, note: str = "", recurrence: str = "",
                          alarm: bool = False, conversation_id: int | None = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO companion_calendar (contact_id, due_at, kind, note, recurrence, alarm, conversation_id) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (contact_id, due_at, kind, note, recurrence, int(bool(alarm)), conversation_id))
            conn.commit()
            return cursor.lastrowid

    def due_companion_rows(self, now: str) -> list[dict]:
        """pending rows due at or before now, oldest first, with the contact's user_id"""
        with self.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT r.*, c.user_id FROM companion_calendar r JOIN contacts c ON c.id = r.contact_id
                WHERE r.status = 'pending' AND r.due_at <= ? AND {self._COMPANION}
                ORDER BY r.due_at, r.id
            """, (now,)).fetchall()
            return [dict(row) for row in rows]

    def next_companion_due(self) -> str | None:
        with self.get_connection() as conn:
            row = conn.execute(f"""
                SELECT MIN(r.due_at) AS due_at FROM companion_calendar r JOIN contacts c ON c.id = r.contact_id
                WHERE r.status = 'pending' AND {self._COMPANION}
            """).fetchone()
            return row["due_at"]

    def finish_companion_row(self, row_id: int, status: str, fired_at: str, result: str = "", message_id: int | None = None, next_due: str | None = None) -> bool:
        """next_due re-arms a recurring row (it stays pending), otherwise the row gets status.
        fired_at None (a missed row): the last run stays as it was"""
        with self.get_connection() as conn:
            if fired_at is None:
                cursor = conn.execute("UPDATE companion_calendar SET status = ?, due_at = COALESCE(?, due_at) WHERE id = ?",
                                      ("pending" if next_due else status, next_due, row_id))
                conn.commit()
                return cursor.rowcount == 1
            cursor = conn.execute("""
                UPDATE companion_calendar SET status = ?, due_at = COALESCE(?, due_at), fired_at = ?, result = ?, message_id = ?
                WHERE id = ?
            """, ("pending" if next_due else status, next_due, fired_at, result, message_id, row_id))
            conn.commit()
            return cursor.rowcount == 1

    def get_companion_day(self, contact_id: int, start: str, end: str) -> list[dict]:
        """the companion's own rows due or fired in [start, end), in time order (not the user's tasks)"""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM companion_calendar WHERE contact_id = ? AND kind != ?
                AND ((due_at >= ? AND due_at < ?) OR (fired_at >= ? AND fired_at < ?))
                ORDER BY COALESCE(fired_at, due_at), id
            """, (contact_id, self.TASK_KIND, start, end, start, end)).fetchall()
            return [dict(row) for row in rows]

    def last_companion_result(self, contact_id: int, kind: str) -> str:
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT result FROM companion_calendar WHERE contact_id = ? AND kind = ? AND fired_at IS NOT NULL AND result != ''
                ORDER BY fired_at DESC LIMIT 1
            """, (contact_id, kind)).fetchone()
            return row["result"] if row else ""

    def count_companion_messages(self, contact_id: int, since: str) -> int:
        """proactive messages sent since (the user's tasks are no proactive messages)"""
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT COUNT(*) FROM companion_calendar WHERE contact_id = ? AND message_id IS NOT NULL AND fired_at >= ? AND kind != ?
            """, (contact_id, since, self.TASK_KIND)).fetchone()
            return row[0]

    def count_pending_companion_rows(self, contact_id: int) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM companion_calendar WHERE contact_id = ? AND status = 'pending' AND recurrence = '' AND kind != ?",
                               (contact_id, self.TASK_KIND)).fetchone()
            return row[0]

    def has_companion_row(self, contact_id: int, due_at: str, kind: str, note: str) -> bool:
        """the same kind at the same time, or the same kind and note still pending: models like to plan things twice"""
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT 1 FROM companion_calendar WHERE contact_id = ? AND kind = ? AND (due_at = ? OR (status = 'pending' AND note = ?))
            """, (contact_id, kind, due_at, note)).fetchone()
            return row is not None

    COMPANION_LOG_KEEP = 50

    def add_companion_log(self, contact_id: int, at: str, record: dict) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("INSERT INTO companion_log (contact_id, at, record) VALUES (?, ?, ?)",
                                  (contact_id, at, json.dumps(record, ensure_ascii=False)))
            conn.execute("""
                DELETE FROM companion_log WHERE contact_id = ? AND id NOT IN
                (SELECT id FROM companion_log WHERE contact_id = ? ORDER BY id DESC LIMIT ?)
            """, (contact_id, contact_id, self.COMPANION_LOG_KEEP))
            conn.commit()
            return cursor.lastrowid

    def get_companion_log(self, contact_id: int | None = None, limit: int = 20) -> list[dict]:
        """the last entries, oldest first, of one contact or of all"""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM companion_log WHERE ? IS NULL OR contact_id = ? ORDER BY id DESC LIMIT ?
            """, (contact_id, contact_id, limit)).fetchall()
            return [{**dict(row), "record": json.loads(row["record"])} for row in reversed(rows)]

    def companion_contacts(self, user_name: str | None = None, contact_id: int | None = None) -> list[dict]:
        """hub management: one contact, all contacts of a user, or else the companions and contacts with a companion log"""
        with self.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT c.id, c.name, c.user_id, u.username, {self._COMPANION} AS companion,
                    (SELECT COUNT(*) FROM companion_calendar r WHERE r.contact_id = c.id AND r.status = 'pending') AS pending,
                    (SELECT MAX(at) FROM companion_log l WHERE l.contact_id = c.id) AS last_pass
                FROM contacts c JOIN users u ON u.id = c.user_id
                WHERE CASE WHEN ? IS NOT NULL THEN c.id = ? WHEN ? IS NOT NULL THEN u.username = ?
                    ELSE {self._COMPANION} OR EXISTS (SELECT 1 FROM companion_log l WHERE l.contact_id = c.id) END
                ORDER BY c.id
            """, (contact_id, contact_id, user_name, user_name)).fetchall()
            return [dict(row) for row in rows]

    def pending_companion_rows(self, contact_id: int) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM companion_calendar WHERE contact_id = ? AND status = 'pending' ORDER BY due_at, id",
                                (contact_id,)).fetchall()
            return [dict(row) for row in rows]

    ########### #170 the user's tasks: rows of kind TASK_KIND in the companion calendar, see app.companion.user_tasks

    def get_tasks(self, user_id: int, contact_id: int | None = None, task_id: int | None = None) -> list[dict]:
        """the user's open (pending) tasks, all, of one contact or one, next first, with contact_name"""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT r.*, c.name AS contact_name FROM companion_calendar r JOIN contacts c ON c.id = r.contact_id
                WHERE c.user_id = ? AND r.kind = ? AND r.status = 'pending' AND (? IS NULL OR r.contact_id = ?) AND (? IS NULL OR r.id = ?)
                ORDER BY r.due_at, r.id
            """, (user_id, self.TASK_KIND, contact_id, contact_id, task_id, task_id)).fetchall()
            return [dict(row) for row in rows]

    def count_tasks(self, user_id: int) -> int:
        """the user's open tasks over all contacts"""
        with self.get_connection() as conn:
            return conn.execute("""
                SELECT COUNT(*) FROM companion_calendar r JOIN contacts c ON c.id = r.contact_id
                WHERE c.user_id = ? AND r.kind = ? AND r.status = 'pending'
            """, (user_id, self.TASK_KIND)).fetchone()[0]

    def update_task(self, user_id: int, task_id: int, due_at: str, recurrence: str, note: str, alarm: bool) -> bool:
        """changes an open task of the user, False if there is none with that id"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE companion_calendar SET due_at = ?, recurrence = ?, note = ?, alarm = ?
                WHERE id = ? AND kind = ? AND status = 'pending' AND contact_id IN (SELECT id FROM contacts WHERE user_id = ?)
            """, (due_at, recurrence, note, int(bool(alarm)), task_id, self.TASK_KIND, user_id))
            conn.commit()
            return cursor.rowcount == 1

    def adopt_tasks(self, contact_id: int, conversation_id: int) -> int:
        """the contact's open tasks without a conversation (it was deleted, or there was none) post into conversation_id"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE companion_calendar SET conversation_id = ?
                WHERE contact_id = ? AND kind = ? AND status = 'pending' AND conversation_id IS NULL
            """, (conversation_id, contact_id, self.TASK_KIND))
            conn.commit()
            return cursor.rowcount

    def delete_task(self, user_id: int, task_id: int) -> bool:
        """cancels an open task of the user, False if there is none with that id"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM companion_calendar
                WHERE id = ? AND kind = ? AND status = 'pending' AND contact_id IN (SELECT id FROM contacts WHERE user_id = ?)
            """, (task_id, self.TASK_KIND, user_id))
            conn.commit()
            return cursor.rowcount == 1


    def set_companion_row_message(self, row_id: int, message_id: int) -> bool:
        """the pass already finished; the message was posted later from a held reach-out (#167, in memory)"""
        with self.get_connection() as conn:
            cursor = conn.execute("UPDATE companion_calendar SET message_id = ? WHERE id = ?", (message_id, row_id))
            conn.commit()
            return cursor.rowcount == 1

    def last_user_message_time(self, contact_id: int) -> str | None:
        """UTC timestamp of the user's last message to this contact, any conversation"""
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT MAX(m.timestamp) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                WHERE c.contact_id = ? AND m.role = 'user'
            """, (contact_id,)).fetchone()
            return row[0]
