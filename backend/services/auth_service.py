import hashlib
import secrets

from database.connection import get_connection


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(username: str, password: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, is_active)
            VALUES (?, ?, 1)
            """,
            (username, hash_password(password)),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def authenticate_user(username: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, password_hash, is_active
        FROM users
        WHERE username = ?
        """,
        (username,),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    user = dict(row)

    if user["is_active"] != 1:
        return None

    if not secrets.compare_digest(user["password_hash"], hash_password(password)):
        return None

    return {
        "id": user["id"],
        "username": user["username"],
    }


def user_exists(username: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    )

    row = cursor.fetchone()
    conn.close()

    return row is not None