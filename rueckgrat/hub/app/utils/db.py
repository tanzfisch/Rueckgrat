import sqlite3
import json

from app.common import Logger
logger = Logger(__name__).get_logger()

class ChatDB:
    def __init__(self, db_path):
        self.db_path = db_path

        logger.info(f"db path is: {db_path}")
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            gender TEXT CHECK(gender IN ('male', 'female')) DEFAULT NULL,
            role TEXT,
            persona TEXT,
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
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, timestamp)
        """)        

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

        conn.commit()
        conn.close()

        logger.info("Database initialized")

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def create_user(self, username: str, passwd: str = None) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, passwd)
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
                "SELECT id, username, password, created_at FROM users WHERE username = ?",
                (user_name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None 

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
            "name", "gender", "role", "persona"
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

                # Return True if a row was actually updated
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

                # Convert row → dict
                contact = dict(row)

                # Deserialize JSON fields
                if contact.get("rules"):
                    try:
                        contact["rules"] = json.loads(contact["rules"])
                    except Exception:
                        # If parsing fails, return raw string as fallback
                        pass

                profile = json.loads(contact["profile"])
                contact.pop("profile")
                contact["profile"] = profile

                return contact

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

                    profile = json.loads(contact["profile"])
                    contact.pop("profile")
                    contact["profile"] = profile

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
                start_context = ""
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO conversations (user_id, contact_id, context)
                    VALUES (?, ?, ?)
                """, (user_id, contact_id, start_context))

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