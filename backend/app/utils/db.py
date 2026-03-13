import sqlite3
import json

class ChatDB:
    def __init__(self, db_path):
        print(f"db path is: {db_path}")

        self.db_path = db_path
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            gender TEXT CHECK(gender IN ('male', 'female')) DEFAULT NULL,
            attributes TEXT,
            core_traits TEXT,
            quirks TEXT,
            distinctive_feature TEXT,
            purpose TEXT,
            relationship TEXT,
            long_term_commitment TEXT,
            current_status TEXT,
            secrets TEXT,
            limits TEXT,
            location TEXT,
            rules TEXT,
            piper_voice_model TEXT,
            kokoro_voice_type TEXT,
            visual_prompt TEXT,
            visual_negative_prompt TEXT,
            visual_seed INTEGER DEFAULT 1337,
            visual_cfg REAL DEFAULT 10 CHECK(visual_cfg > 0),
            visual_steps INTEGER DEFAULT 30 CHECK(visual_steps > 0),
            chat_temperature REAL DEFAULT 0.7 CHECK(chat_temperature >= 0 AND chat_temperature <= 2),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

            UNIQUE(user_id, name)
        );""")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            title TEXT,
            brief TEXT DEFAULT "New Conversation",
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        )""")                

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'error')),
            content TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )""")

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

        print("Database initialized")

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
                print("created user")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError("Username already exists")

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

    def create_empty_contact(self, user_id: int, contact_name: str) -> int:
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
                print(f"Error: failed creating contact: {e}")
                
        return -1    

    def create_contact(self, user_id: int, contact_json: dict):
        """
        Create a new contact in the contacts table.

        :param user_id: ID of the user who owns this contact
        :param contact_json: Dictionary containing contact fields
        """

        allowed_fields = [
            "name", "gender", "attributes", "core_traits", "quirks",
            "distinctive_feature", "purpose", "relationship", "long_term_commitment",
            "current_status", "secrets", "limits", "location",
            "visual_prompt", "visual_negative_prompt", "visual_seed",
            "visual_cfg", "visual_steps", "chat_temperature",
            "rules", "piper_voice_model", "kokoro_voice_type"
        ]

        with self.get_connection() as conn:
            fields = ["user_id"]
            values = [user_id]

            for key in allowed_fields:
                if key in contact_json:
                    value = contact_json[key]

                    # Serialize rules array to JSON string
                    if key == "rules" and isinstance(value, list):
                        value = json.dumps(value)

                    fields.append(key)
                    values.append(value)

            placeholders = ",".join(["?"] * len(fields))
            columns = ",".join(fields)

            query = f"""
                INSERT INTO contacts ({columns})
                VALUES ({placeholders})
            """

            try:
                cursor = conn.cursor()
                cursor.execute(query, values)
                conn.commit()
                return cursor.lastrowid

            except sqlite3.IntegrityError as e:
                print(f"Integrity error: {e}")
                return None

            except Exception as e:
                print(f"Error creating contact: {e}")
                return None

    def update_contact(self, user_id: int, contact_id: int, contact_json: dict):
        """
        Update an existing contact in the contacts table.

        :param user_id: ID of the user who owns this contact
        :param contact_id: ID of the contact to update
        :param contact_json: Dictionary containing fields to update
        """

        allowed_fields = [
            "name", "gender", "attributes", "core_traits", "quirks",
            "distinctive_feature", "purpose", "relationship", "long_term_commitment",
            "current_status", "secrets", "limits", "location",
            "visual_prompt", "visual_negative_prompt", "visual_seed",
            "visual_cfg", "visual_steps", "chat_temperature",
            "rules"
        ]

        with self.get_connection() as conn:
            updates = []
            values = []

            for key in allowed_fields:
                if key in contact_json:
                    value = contact_json[key]

                    # Serialize rules array to JSON string
                    if key == "rules" and isinstance(value, list):
                        value = json.dumps(value)

                    updates.append(f"{key} = ?")
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
                print(f"Integrity error: {e}")
                return False

            except Exception as e:
                print(f"Error updating contact: {e}")
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

                return contact

            except Exception as e:
                print(f"Error retrieving contact: {e}")
                return None                
            
    def get_contacts(self, user_id: int):
        """
        Retrieve all contacts for a given user_id.
        Returns a list of contact dictionaries.
        """

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

                    contacts.append(contact)

                return contacts

            except Exception as e:
                print(f"Error: retrieving contacts: {e}")
                return []        

    def get_conversations(self, user_id: int, contact_id: int):
        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT id, user_id, contact_id, title, brief, created_at
                    FROM conversations
                    WHERE user_id = ?
                    AND contact_id = ?
                    ORDER BY created_at DESC
                """, (user_id, contact_id))

                rows = cursor.fetchall()
                conversations = [dict(row) for row in rows]
                return conversations                
            
            except Exception as e:
                print(f"Error: retrieving conversations: {e}")
                
        return []             
            
    def create_conversation(self, user_id: int, contact_id: int) -> int:
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO conversations (user_id, contact_id)
                    VALUES (?, ?)
                """, (user_id, contact_id))

                conn.commit()
                return cursor.lastrowid
            
            except Exception as e:
                print(f"Error: failed creating conversation: {e}")
                
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
                print(f"Error: failed deleting conversation: {e}")

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
                print(f"Error: failed deleting contact: {e}")

        return False

    def get_messages_by_conversation(self, conversation_id: int):
        with self.get_connection() as conn:
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT role, content, timestamp
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC
                """, (conversation_id,))

                return [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                print(f"Error: failed returning messages: {e}")         

    def add_message(self, conversation_id: int, role: str, content: str) -> int:
        valid_roles = {"user", "assistant", "system", "error"}

        if role not in valid_roles:
            raise ValueError(f"Invalid role: {role}")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO messages (conversation_id, role, content)
                VALUES (?, ?, ?)
            """, (conversation_id, role, content))

            return cursor.lastrowid    