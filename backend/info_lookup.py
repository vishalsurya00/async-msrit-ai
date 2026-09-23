"""
Information lookup module for MSRIT AI.
Provides lookups for campus branches, student clubs, and subject listings.
"""
from typing import Optional, List, Dict, Any
import sys
from db.connection import get_connection


def lookup_branch(query: str) -> Optional[Dict[str, Any]]:
    """
    Search branches table by code or name (ILIKE partial match).
    Returns a single dictionary matching the query or None if not found.
    """
    if not query or not query.strip():
        return None

    try:
        conn = get_connection()
        cur = conn.cursor()
        search_pattern = f"%{query.strip()}%"
        cur.execute(
            """
            SELECT code, name, stream, hod_name, location
            FROM branches
            WHERE code ILIKE %s OR name ILIKE %s
            LIMIT 1;
            """,
            (search_pattern, search_pattern)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return {
            "code": row[0],
            "name": row[1],
            "stream": row[2],
            "hod_name": row[3],
            "location": row[4]
        }

    except Exception as e:
        print(f"Error in lookup_branch: {e}", file=sys.stderr)
        return None


def lookup_club(
    query: Optional[str] = None,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search clubs table by name or category (ILIKE).
    If neither parameter is provided, returns all clubs.
    """
    try:
        where_clauses = []
        params = []

        if query and query.strip():
            pattern = f"%{query.strip()}%"
            where_clauses.append("(name ILIKE %s OR description ILIKE %s)")
            params.extend([pattern, pattern])

        if category and category.strip():
            cat_pattern = f"%{category.strip()}%"
            where_clauses.append("category ILIKE %s")
            params.append(cat_pattern)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT id, name, category, lead_name, description
            FROM clubs
            {where_sql}
            ORDER BY name ASC;
        """

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [
            {
                "id": row[0],
                "name": row[1],
                "category": row[2],
                "lead_name": row[3],
                "description": row[4]
            }
            for row in rows
        ]

    except Exception as e:
        print(f"Error in lookup_club: {e}", file=sys.stderr)
        return []


def list_subjects(
    stream: Optional[str] = None,
    cycle: Optional[str] = None
) -> List[str]:
    """
    List distinct subjects from notes_chunks with optional stream/cycle filters.
    If the subject column is unpopulated, extracts subjects from ingested file paths.
    """
    try:
        where_clauses = []
        params = []

        if stream and stream.strip():
            s_val = stream.strip()
            where_clauses.append("(stream ILIKE %s OR stream ILIKE %s)")
            params.extend([s_val, f"%{s_val}%"])

        if cycle and cycle.strip():
            c_val = cycle.strip()
            where_clauses.append("(cycle ILIKE %s OR cycle ILIKE %s)")
            params.extend([c_val, f"%{c_val}%"])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        conn = get_connection()
        cur = conn.cursor()

        # Check explicit subject column first
        cur.execute(
            f"""
            SELECT DISTINCT subject 
            FROM notes_chunks 
            {where_sql}
            """,
            params
        )
        rows = cur.fetchall()
        subjects = [r[0].strip() for r in rows if r[0] and r[0].strip()]

        if not subjects:
            # Fallback to extracting subject folder names from file_path
            cur.execute(
                f"""
                SELECT DISTINCT file_path 
                FROM notes_chunks 
                {where_sql}
                """,
                params
            )
            fp_rows = cur.fetchall()
            extracted = set()
            for (fp,) in fp_rows:
                parts = (fp or "").replace("\\", "/").split("/")
                for part in parts:
                    if "__" in part:
                        sub_name = part.split("__")[0].replace("_", " ").capitalize()
                        extracted.add(sub_name)
            subjects = sorted(list(extracted))

        cur.close()
        conn.close()
        return sorted(list(set(subjects)))

    except Exception as e:
        print(f"Error in list_subjects: {e}", file=sys.stderr)
        return []
