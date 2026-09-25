"""
Information lookup module for MSRIT AI.
Provides lookups for campus branches, student clubs, and subject listings.
"""
from typing import Optional, List, Dict, Any
import re
import sys
from db.connection import get_connection

BRANCH_ALIASES: Dict[str, str] = {
    # Civil
    "cv": "CE",
    "civil": "CE",
    "civil engineering": "CE",
    "ce": "CE",
    # Mechanical
    "me": "ME",
    "mech": "ME",
    "mechanical": "ME",
    "mechanical engineering": "ME",
    # AI & ML
    "aiml": "AI&ML",
    "ai ml": "AI&ML",
    "ai&ml": "AI&ML",
    "ai and ml": "AI&ML",
    "artificial intelligence & machine learning": "AI&ML",
    "artificial intelligence and machine learning": "AI&ML",
    # CSE
    "cse": "CSE",
    "cs": "CSE",
    "computer science": "CSE",
    "computer science & engineering": "CSE",
    "computer science and engineering": "CSE",
    # Cyber Security
    "cyber security": "CSE(CS)",
    "cybersecurity": "CSE(CS)",
    "cse(cyber security)": "CSE(CS)",
    "cse(cs)": "CSE(CS)",
    "cse cs": "CSE(CS)",
    "cse cyber security": "CSE(CS)",
    "cse-cs": "CSE(CS)",
    # CSE AIML
    "cse(aiml)": "CSE(AIML)",
    "cse aiml": "CSE(AIML)",
    "cse-aiml": "CSE(AIML)",
    # ISE
    "ise": "ISE",
    "information science": "ISE",
    "information science & engineering": "ISE",
    "information science and engineering": "ISE",
    "is dept": "ISE",
    "is department": "ISE",
    # AIDS
    "aids": "AIDS",
    "ai ds": "AIDS",
    "ai data science": "AIDS",
    "artificial intelligence & data science": "AIDS",
    "artificial intelligence and data science": "AIDS",
    # ECE
    "ece": "ECE",
    "electronics": "ECE",
    "electronics & communication engineering": "ECE",
    "electronics and communication engineering": "ECE",
    # EEE
    "eee": "EEE",
    "electrical": "EEE",
    "electrical & electronics engineering": "EEE",
    # EIE
    "eie": "EIE",
    "instrumentation": "EIE",
    "electronics & instrumentation engineering": "EIE",
    # ETE
    "ete": "ETE",
    "telecom": "ETE",
    "telecommunication engineering": "ETE",
    # BT
    "bt": "BT",
    "biotech": "BT",
    "biotechnology": "BT",
    # CHE
    "che": "CHE",
    "chem": "CHE",
    "chemical": "CHE",
    "chemical engineering": "CHE",
    # AE
    "ae": "AE",
    "aero": "AE",
    "aerospace": "AE",
    "aerospace engineering": "AE",
    # IEM
    "iem": "IEM",
    "industrial": "IEM",
    "industrial engineering & management": "IEM",
    # MLE
    "mle": "MLE",
    "medical electronics": "MLE",
    "medical electronics engineering": "MLE",
    # Architecture
    "arch": "B-Arch",
    "barch": "B-Arch",
    "b-arch": "B-Arch",
    "architecture": "B-Arch",
}

AMBIGUOUS_ALIASES = {"me"}

_CLUBS_CACHE: Optional[Dict[str, str]] = None


def get_club_lookup_map() -> Dict[str, str]:
    """
    Returns a dictionary mapping normalized club names, acronyms, and aliases
    to their canonical club name dynamically from PostgreSQL.
    """
    global _CLUBS_CACHE
    if _CLUBS_CACHE is not None:
        return _CLUBS_CACHE

    club_map: Dict[str, str] = {}
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM clubs;")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for (name,) in rows:
            clean_name = name.strip()
            club_map[clean_name.lower()] = clean_name
            # Acronym in parentheses e.g. "National Service Scheme (NSS)"
            m = re.search(r'\(([^)]+)\)', clean_name)
            if m:
                club_map[m.group(1).lower().strip()] = clean_name
            # Subteam e.g. "Aero Club - Team Editha" or "SAE Club - Team Velocita"
            if " - Team " in clean_name:
                sub = clean_name.split(" - Team ")[-1].strip()
                club_map[sub.lower()] = clean_name
                club_map[f"team {sub.lower()}"] = clean_name
            elif " - " in clean_name:
                sub = clean_name.split(" - ")[-1].strip()
                club_map[sub.lower()] = clean_name
            # Standard abbreviations
            if "Google Developers" in clean_name:
                club_map["gdsc"] = clean_name
                club_map["google developers"] = clean_name
    except Exception as e:
        print(f"Warning: Could not fetch clubs dynamically from database: {e}", file=sys.stderr)

    _CLUBS_CACHE = club_map
    return _CLUBS_CACHE


_FACULTY_CACHE: Optional[List[Dict[str, Any]]] = None


def normalize_faculty_name(name: str) -> str:
    """
    Normalizes person/faculty name by lowercasing, stripping titles/honorifics,
    removing punctuation (periods, commas, hyphens), and collapsing whitespace.
    """
    s = name.lower()
    s = re.sub(r'\b(dr|prof|professor|mr|mrs|ms)\b', '', s)
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def get_faculty_lookup_map() -> List[Dict[str, Any]]:
    """
    Dynamically loads faculty/HOD entries from the branches table in PostgreSQL.
    Groups multiple departments belonging to the same HOD (e.g. Dr. Siddesh G. M.).
    Returns a list of structured faculty metadata entries.
    """
    global _FACULTY_CACHE
    if _FACULTY_CACHE is not None:
        return _FACULTY_CACHE

    faculty_dict: Dict[str, Dict[str, Any]] = {}
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT code, name, hod_name, location, stream FROM branches;")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for code, name, hod, loc, stream in rows:
            if not hod or not hod.strip():
                continue
            canonical_hod = hod.strip()
            # Normalize trailing period if not an initial (e.g. 'Dr. Jayaram R. Pothnis.')
            if canonical_hod.endswith(".") and not re.search(r'\b[A-Z]\.$', canonical_hod):
                canonical_hod = canonical_hod[:-1].strip()

            norm_name = normalize_faculty_name(canonical_hod)
            if canonical_hod not in faculty_dict:
                tokens = norm_name.split()
                no_initials = " ".join([t for t in tokens if len(t) > 1])
                faculty_dict[canonical_hod] = {
                    "canonical_name": canonical_hod,
                    "normalized": norm_name,
                    "no_initials": no_initials,
                    "tokens": tokens,
                    "long_tokens": [t for t in tokens if len(t) >= 4],
                    "departments": []
                }

            faculty_dict[canonical_hod]["departments"].append({
                "code": code,
                "name": name,
                "location": loc,
                "stream": stream
            })
    except Exception as e:
        print(f"Warning: Could not fetch faculty dynamically from database: {e}", file=sys.stderr)

    _FACULTY_CACHE = list(faculty_dict.values())
    return _FACULTY_CACHE


def lookup_faculty(query: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically search faculty/HOD records loaded from branches table.
    Matches normalized name variants (ignoring case, periods, commas, honorifics).
    Returns dict with 'canonical_name' and 'departments' list, or None.
    """
    if not query or not query.strip():
        return None

    clean_q = normalize_faculty_name(query)
    faculty_list = get_faculty_lookup_map()

    # 1. Match full normalized name (e.g. 'siddesh g m', 'r china appala naidu')
    for f in faculty_list:
        if f["normalized"]:
            pat = r'(?:\b|^)' + re.escape(f["normalized"]) + r'(?:\b|$)'
            if re.search(pat, clean_q):
                return {
                    "canonical_name": f["canonical_name"],
                    "departments": f["departments"]
                }

    # 2. Match without initials (e.g. 'china appala naidu', 'jagadish kallimani')
    for f in faculty_list:
        if f["no_initials"] and len(f["no_initials"].split()) >= 2:
            pat = r'(?:\b|^)' + re.escape(f["no_initials"]) + r'(?:\b|$)'
            if re.search(pat, clean_q):
                return {
                    "canonical_name": f["canonical_name"],
                    "departments": f["departments"]
                }

    # 3. Match distinct single non-initial name if query specifically mentions doctor/prof or name
    # e.g. 'Dr Siddesh', 'Dr Subramanian', 'Tell me about Dr Siddesh'
    has_faculty_title = bool(re.search(r'\b(dr|prof|professor|hod|head)\b', query.lower()))
    if has_faculty_title:
        for f in faculty_list:
            for lt in f["long_tokens"]:
                if len(lt) >= 5:
                    pat = r'(?:\b|^)' + re.escape(lt) + r'(?:\b|$)'
                    if re.search(pat, clean_q):
                        return {
                            "canonical_name": f["canonical_name"],
                            "departments": f["departments"]
                        }

    return None



def find_branch_code(query: str) -> Optional[str]:
    """
    Match user query terms against BRANCH_ALIASES with strict priority:
    1. Direct full string match on clean query.
    2. Stripped department query check (e.g. 'hod cse' -> 'cse').
    3. Unambiguous aliases from longest to shortest.
    4. Ambiguous alias ('me') only if accompanied by clear mechanical department context.
    Never matches generic English 'is' or 'me'.
    """
    if not query or not query.strip():
        return None

    raw_stripped = query.strip()
    lower = raw_stripped.lower()

    # 1. Direct full string match (e.g. 'cse', 'ise', 'me', 'mechanical')
    if lower in BRANCH_ALIASES:
        return BRANCH_ALIASES[lower]

    # 2. Check if query minus common department words is literally an alias (excluding ambiguous 'me')
    dept_stripped = re.sub(
        r'\b(hod|head\s+of(?:\s+department)?|department|dept|office|where\s+is|who\s+is|branch|details|information)\b',
        '',
        lower
    ).strip()
    dept_stripped = re.sub(r'^(of|the|for|about)\s+', '', dept_stripped).strip()
    dept_stripped = re.sub(r'\s+(of|the|for|about)$', '', dept_stripped).strip()
    if dept_stripped in BRANCH_ALIASES and dept_stripped not in AMBIGUOUS_ALIASES:
        return BRANCH_ALIASES[dept_stripped]

    # 3. Priority: Check all unambiguous aliases from longest to shortest
    sorted_aliases = [a for a in sorted(BRANCH_ALIASES.keys(), key=len, reverse=True) if a not in AMBIGUOUS_ALIASES]
    for alias in sorted_aliases:
        pat = r'(?:\b|^)' + re.escape(alias) + r'(?:\b|$)'
        if re.search(pat, lower):
            return BRANCH_ALIASES[alias]

    # 4. For ambiguous 'me', only match if clearly in mechanical department context (never 'where is me?' or 'help me')
    pat_me = (
        r'(?:\b(?:hod|head)\s+(?:of\s+)?me\b'
        r'|\bme\s+(?:department|dept|branch|office|hod)\b'
        r'|\b(?:department|dept|branch)\s+of\s+me\b)'
    )
    if re.search(pat_me, lower):
        return "ME"

    return None


def lookup_branch(query: str) -> Optional[Dict[str, Any]]:
    """
    Search branches table by code or name using fuzzy and flexible alias mapping.
    Matches aliases to canonical branch codes first, then prioritizes exact/alias matches in PostgreSQL.
    Returns matched branch dict with keys: code, name, stream, hod_name, location.
    """
    if not query or not query.strip():
        return None

    clean_q = query.strip()
    matched_code = find_branch_code(clean_q)

    try:
        conn = get_connection()
        cur = conn.cursor()

        # 1. If an alias mapped to a canonical branch code, try direct code lookup first
        if matched_code:
            cur.execute(
                """
                SELECT code, name, stream, hod_name, location
                FROM branches
                WHERE code = %s OR code ILIKE %s
                LIMIT 1;
                """,
                (matched_code, matched_code)
            )
            row = cur.fetchone()
            if row:
                cur.close()
                conn.close()
                return {
                    "code": row[0],
                    "name": row[1],
                    "stream": row[2],
                    "hod_name": row[3],
                    "location": row[4]
                }

        # 2. General search with prioritization (exact match -> code ILIKE -> name ILIKE)
        search_pattern = f"%{clean_q}%"
        cur.execute(
            """
            SELECT code, name, stream, hod_name, location
            FROM branches
            WHERE code ILIKE %s OR name ILIKE %s
            ORDER BY 
                CASE 
                    WHEN LOWER(code) = LOWER(%s) THEN 1
                    WHEN LOWER(name) = LOWER(%s) THEN 2
                    WHEN code ILIKE %s THEN 3
                    ELSE 4
                END
            LIMIT 1;
            """,
            (search_pattern, search_pattern, clean_q, clean_q, f"%{clean_q}%")
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
