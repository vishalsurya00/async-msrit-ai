"""
Memory module for MSRIT AI.
Handles persistent student profile storage and retrieval in PostgreSQL.
"""
from typing import Optional, Dict, Any
import sys
import json
import psycopg2.extras
from db.connection import get_connection

ALLOWED_PROFILE_FIELDS = {
    "name",
    "college",
    "degree",
    "branch",
    "semester",
    "year",
    "stream",
    "cycle",
    "cgpa",
    "preferences",
}


def get_student_profile(student_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a student's profile from student_profile table.
    Returns a dictionary of all stored profile fields or None if not found.
    """
    if not student_id or not student_id.strip():
        return None

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT student_id, name, college, degree, branch, semester, year, stream, cycle, cgpa, preferences, updated_at
            FROM student_profile
            WHERE student_id = %s;
            """,
            (student_id.strip(),)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return {
            "student_id": row[0],
            "name": row[1],
            "college": row[2],
            "degree": row[3],
            "branch": row[4],
            "semester": row[5],
            "year": row[6],
            "stream": row[7],
            "cycle": row[8],
            "cgpa": float(row[9]) if row[9] is not None else None,
            "preferences": row[10] if row[10] is not None else {},
            "updated_at": row[11].isoformat() if row[11] else None
        }

    except Exception as e:
        print(f"Error in get_student_profile: {e}", file=sys.stderr)
        return None


def update_student_profile(student_id: str, **fields) -> Dict[str, Any]:
    """
    Upsert student profile record. Only updates fields that were explicitly passed (PATCH behavior).
    Preserves all existing unmentioned fields in the record.
    Always updates the updated_at timestamp.
    Returns the resulting profile row as a dictionary.
    """
    if not student_id or not student_id.strip():
        return {}

    try:
        clean_id = student_id.strip()
        filtered_fields = {k: v for k, v in fields.items() if k in ALLOWED_PROFILE_FIELDS and v is not None}

        columns = ["student_id"]
        placeholders = ["%s"]
        values = [clean_id]
        update_clauses = []

        for col, val in filtered_fields.items():
            columns.append(col)
            placeholders.append("%s")
            if col == "preferences" and isinstance(val, (dict, list)):
                values.append(psycopg2.extras.Json(val))
            elif col in ("semester", "year") and val is not None:
                try:
                    values.append(int(val))
                except (ValueError, TypeError):
                    values.append(None)
            elif col == "cgpa" and val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    values.append(None)
            else:
                values.append(str(val).strip() if isinstance(val, str) else val)
            update_clauses.append(f"{col} = EXCLUDED.{col}")

        update_clauses.append("updated_at = CURRENT_TIMESTAMP")
        columns_sql = ", ".join(columns)
        placeholders_sql = ", ".join(placeholders)
        update_sql = ", ".join(update_clauses)

        sql = f"""
            INSERT INTO student_profile ({columns_sql}, updated_at)
            VALUES ({placeholders_sql}, CURRENT_TIMESTAMP)
            ON CONFLICT (student_id)
            DO UPDATE SET {update_sql}
            RETURNING student_id, name, college, degree, branch, semester, year, stream, cycle, cgpa, preferences, updated_at;
        """

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql, values)
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not row:
            return {}

        return {
            "student_id": row[0],
            "name": row[1],
            "college": row[2],
            "degree": row[3],
            "branch": row[4],
            "semester": row[5],
            "year": row[6],
            "stream": row[7],
            "cycle": row[8],
            "cgpa": float(row[9]) if row[9] is not None else None,
            "preferences": row[10] if row[10] is not None else {},
            "updated_at": row[11].isoformat() if row[11] else None
        }

    except Exception as e:
        print(f"Error in update_student_profile: {e}", file=sys.stderr)
        return {}
