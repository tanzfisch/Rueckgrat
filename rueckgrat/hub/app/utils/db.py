import sqlite3
import json
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.common import get_logger
logger = get_logger()

class ChatDB:
    def __init__(self, db_path):
        self.db_path = db_path

        logger.debug(f"db path is: {db_path}")
        conn = self.get_connection()
        cursor = conn.cursor()

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
            type TEXT CHECK(type IN ('profile', 'gallery')) DEFAULT 'profile',
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
            title TEXT DEFAULT "...",
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER PRIMARY KEY,
            profile TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")

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

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_voices_contact
            ON voices(contact_id) WHERE contact_id IS NOT NULL
        """)

        conn.commit()
        conn.close()

        logger.info("Database initialized")

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
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
                "SELECT id, username, hashed_password, created_at FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None            
        
    def get_users(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, created_at FROM users")
            return [dict(row) for row in cursor.fetchall()]        

    def create_user_data(self, user_id: int, profile: str = None) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO user_data (user_id, profile) VALUES (?, ?)",
                    (user_id, profile)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
        
    def update_user_data(self, user_id: int, user_data: dict):
        allowed_fields = ["profile"]

        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                # Check if row exists
                cursor.execute("SELECT 1 FROM user_data WHERE user_id = ?", (user_id,))
                exists = cursor.fetchone() is not None

                values = []
                for key in allowed_fields:
                    if key in user_data:
                        values.append(user_data[key])

                if not values:
                    return False

                if exists:
                    set_clause = ", ".join(f"{key} = ?" for key in allowed_fields if key in user_data)
                    query = f"UPDATE user_data SET {set_clause} WHERE user_id = ?"
                    values.append(user_id)
                else:
                    cols = ["user_id"] + [k for k in allowed_fields if k in user_data]
                    placeholders = ["?"] * len(cols)
                    query = f"INSERT INTO user_data ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
                    values.insert(0, user_id)

                cursor.execute(query, values)
                conn.commit()
                return cursor.rowcount > 0

            except Exception as e:
                logger.error(f"failed updating user data {e}")
                return False        

    def delete_user_data(self, user_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_data WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_user_data(self, user_id: int) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT profile FROM user_data WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return {"profile": row[0]} if row else None

    def create_contact(self, user_id: int, contact_name: str) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO contacts (user_id, name)
                    VALUES (?, ?)
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

            value = json.dumps(profile)
            updates.append(f"profile = ?")
            values.append(value)

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
                    "profile": json.loads(contact["profile"])
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
                    if contact.get("rules"):
                        try:
                            contact["rules"] = json.loads(contact["rules"])
                        except Exception:
                            pass  # fallback to raw string if malformed

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

                cursor.execute("""
                    SELECT id, user_id, contact_id, title, context, created_at
                    FROM conversations
                    WHERE id = ?
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

    def owns_image(self, user_id: int, file_key: str) -> bool:
        """False for foreign and unknown images alike, an image belongs to the owner of its contact"""
        with self.get_connection() as conn:
            try:
                row = conn.execute("SELECT 1 FROM contact_images ci JOIN contacts c ON c.id = ci.contact_id WHERE ci.file_key = ? AND c.user_id = ?", (file_key, user_id)).fetchone()
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
                        SELECT id, role, name, content, timestamp
                        FROM messages
                        WHERE conversation_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                    ORDER BY timestamp ASC;
                """, (conversation_id, max_messages))

                return [dict(row) for row in cursor.fetchall()]
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

    def find_predefined_voice(self, user_id: int, predefined_id: str, content_hash: str) -> str | None:
        """id of the user's stored copy of a predefined voice, or None.
        old rows without origin (NULL) still match by hash, a row with the exact predefined id wins"""
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM voices
                    WHERE user_id = ? AND (predefined_id = ? OR (predefined_id IS NULL AND content_hash = ?))
                    ORDER BY predefined_id IS NULL
                    LIMIT 1
                """, (user_id, predefined_id, content_hash))
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
                # "no name" instead of NULL: older databases still have created_by NOT NULL
                (self._hash_token(token), created_by or "no name", email.lower() if email else None, expires_at, max_uses, 1 if nsfw_allowed else 0)
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
