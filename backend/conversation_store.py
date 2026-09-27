"""
Conversation storage module for RIT NEXUS.
Provides persistence for conversation sessions and individual messages in PostgreSQL.
Kept strictly separate from core routing logic.
"""
from typing import Optional, Dict, Any, List, Tuple
import uuid
import json
import psycopg2.extras
from db.connection import get_connection


def create_session(student_id: str = "anonymous") -> str:
    """Create a new session in PostgreSQL and return its session_id string."""
    new_uuid = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_sessions (session_id, student_id)
                VALUES (%s, %s)
                RETURNING session_id;
                """,
                (new_uuid, student_id or "anonymous")
            )
            sid = cur.fetchone()[0]
            conn.commit()
            return str(sid)
    finally:
        conn.close()


def session_exists(session_id: str) -> bool:
    """Check if a session_id is a valid UUID and exists in conversation_sessions."""
    if not session_id:
        return False
    try:
        val = uuid.UUID(str(session_id))
    except (ValueError, AttributeError, TypeError):
        return False

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM conversation_sessions WHERE session_id = %s;",
                (str(val),)
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_or_create_session(
    session_id: Optional[str] = None,
    student_id: str = "anonymous"
) -> Tuple[str, bool]:
    """
    Retrieve existing session if valid; otherwise create a fresh session.
    Returns (session_id_str, is_new).
    """
    if session_id and session_exists(session_id):
        # Update updated_at timestamp
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversation_sessions 
                    SET updated_at = CURRENT_TIMESTAMP 
                    WHERE session_id = %s;
                    """,
                    (session_id,)
                )
                conn.commit()
        finally:
            conn.close()
        return session_id, False

    new_sid = create_session(student_id=student_id)
    return new_sid, True


def add_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Append an individual message to conversation_messages.
    Returns the message ID.
    """
    if role not in ("user", "assistant"):
        raise ValueError(f"Invalid message role '{role}'. Must be 'user' or 'assistant'.")

    meta_json = psycopg2.extras.Json(metadata if metadata is not None else {})
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_messages (session_id, role, content, metadata)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (session_id, role, content, meta_json)
            )
            msg_id = cur.fetchone()[0]
            # Also update session updated_at
            cur.execute(
                "UPDATE conversation_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = %s;",
                (session_id,)
            )
            conn.commit()
            return msg_id
    finally:
        conn.close()


def get_recent_messages(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch the most recent N messages for a session, in chronological order.
    Returns list of dicts: [{'role': ..., 'content': ..., 'metadata': ..., 'created_at': ...}].
    """
    if not session_id or not session_exists(session_id):
        return []

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, metadata, created_at
                FROM conversation_messages
                WHERE session_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s;
                """,
                (session_id, limit)
            )
            rows = cur.fetchall()
            # Reverse so the returned list is in chronological order
            ordered = list(reversed(rows))
            return [
                {
                    "role": r[0],
                    "content": r[1],
                    "metadata": r[2] if isinstance(r[2], dict) else {},
                    "created_at": r[3].isoformat() if r[3] else None
                }
                for r in ordered
            ]
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    """Delete a session and all its messages."""
    if not session_id or not session_exists(session_id):
        return False
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversation_sessions WHERE session_id = %s;", (session_id,))
            conn.commit()
            return True
    finally:
        conn.close()
