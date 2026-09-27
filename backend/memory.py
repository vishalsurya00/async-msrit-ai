"""
Memory module for MSRIT AI.
Handles persistent student profile storage and retrieval in PostgreSQL.
"""
from typing import Optional, Dict, Any, List, Tuple
import sys
import json
import re
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

SUPPORTED_PREFERENCE_KEYS = {"explanation_style", "focus_subject"}

SUPPORTED_EXPLANATION_STYLES = {"concise", "detailed"}

EXPLANATION_STYLE_SYNONYMS = {
    "concise": "concise",
    "short": "concise",
    "brief": "concise",
    "direct": "concise",
    "detailed": "detailed",
    "long": "detailed",
    "thorough": "detailed",
    "in-depth": "detailed",
    "in depth": "detailed",
}

SUPPORTED_FIRST_YEAR_SUBJECTS = {
    "mathematics": "Mathematics",
    "maths": "Mathematics",
    "math": "Mathematics",
    "physics": "Physics",
    "phy": "Physics",
    "chemistry": "Chemistry",
    "chem": "Chemistry",
    "programming in c": "Programming in C",
    "c programming": "Programming in C",
    "cprog": "Programming in C",
    "c": "Programming in C",
    "civil engineering": "Civil Engineering",
    "civil": "Civil Engineering",
    "civil engineering (esc)": "Civil Engineering",
}


def normalize_preference_value(key: str, val: Any) -> Tuple[Optional[Any], bool]:
    """
    Validates and normalizes supported preference keys and values.
    Returns (normalized_value, is_valid).
    """
    if key == "explanation_style":
        if isinstance(val, str):
            clean = val.strip().lower()
            clean = re.sub(r'\s+(?:explanations?|answers?|responses?|style)$', '', clean).strip()
            if clean in EXPLANATION_STYLE_SYNONYMS:
                return EXPLANATION_STYLE_SYNONYMS[clean], True
        return None, False

    if key == "focus_subject":
        if isinstance(val, str):
            clean = val.strip().lower()
            clean = re.sub(r'\s+(?:subject|course)$', '', clean).strip()
            if clean in SUPPORTED_FIRST_YEAR_SUBJECTS:
                return SUPPORTED_FIRST_YEAR_SUBJECTS[clean], True
        return None, False

    return None, False


def validate_and_normalize_preferences(raw_prefs: Any) -> Tuple[Dict[str, Any], List[str]]:
    """
    Validates a preferences dictionary or JSON string.
    Only allows 'explanation_style' and 'focus_subject'.
    Returns (valid_preferences_dict, invalid_keys_list).
    """
    if isinstance(raw_prefs, str):
        try:
            raw_prefs = json.loads(raw_prefs)
        except Exception:
            return {}, ["preferences_json"]

    if not isinstance(raw_prefs, dict):
        return {}, ["preferences_type"]

    valid_prefs: Dict[str, Any] = {}
    invalid_keys: List[str] = []

    for k, v in raw_prefs.items():
        if k not in SUPPORTED_PREFERENCE_KEYS:
            invalid_keys.append(k)
            continue
        norm_v, is_valid = normalize_preference_value(k, v)
        if is_valid:
            valid_prefs[k] = norm_v
        else:
            invalid_keys.append(k)

    return valid_prefs, invalid_keys


def normalize_canonical_branch(raw: Optional[str]) -> Optional[str]:
    """
    Normalizes branch input to canonical representation.
    Guarantees:
      - 'AI&ML' and 'CSE(AI&ML)' are different branches.
      - Never normalizes CSE(AI&ML) -> AI&ML.
      - Canonical stored/displayed value for CSE AIML is 'CSE(AI&ML)' (not 'CSE(AIML)').
      - Canonical stored/displayed value for AI&ML is 'AI&ML'.
    """
    if not raw:
        return raw
    clean = str(raw).strip(' .,;:-')
    norm = clean.lower().replace(" ", "").replace("_", "").replace("-", "")

    # 1. CSE(AI&ML) variants: MUST come BEFORE plain AI&ML
    cse_aiml_variants = (
        "cse(ai&ml)", "cse(aiml)", "cseaiml", "cseai&ml", "cseaiandml", "cse(aiandml)",
        "cse-aiml", "cse-ai&ml", "cse/aiml", "cse/ai&ml",
        "computerscienceandengineering(artificialintelligenceandmachinelearning)",
        "computerscienceandengineering(artificialintelligence&machinelearning)",
        "computerscience&engineering(artificialintelligence&machinelearning)",
        "computerscienceandengineeringartificialintelligenceandmachinelearning",
    )
    cse_aiml_strings = (
        "cse(ai&ml)", "cse (ai&ml)", "cse(aiml)", "cse (aiml)", "cse aiml", "cse ai&ml",
        "cse-aiml", "cse-ai&ml", "cse ai and ml", "cse (ai and ml)", "cse(ai and ml)",
        "cse artificial intelligence & machine learning", "cse artificial intelligence and machine learning",
        "computer science and engineering (artificial intelligence and machine learning)",
        "computer science and engineering (artificial intelligence & machine learning)",
        "computer science & engineering (artificial intelligence & machine learning)",
        "computer science and engineering artificial intelligence and machine learning",
    )
    if norm in cse_aiml_variants or clean.lower() in cse_aiml_strings:
        return "CSE(AI&ML)"

    # 2. AI&ML variants (WITHOUT CSE)
    aiml_variants = ("ai&ml", "aiml", "aiandml", "aim&l")
    aiml_strings = (
        "ai&ml", "aiml", "ai ml", "ai and ml",
        "artificial intelligence & machine learning", "artificial intelligence and machine learning"
    )
    if norm in aiml_variants or clean.lower() in aiml_strings:
        return "AI&ML"

    # 3. CSE Cyber Security
    if norm in ("cse(cs)", "csecs", "csecys", "cse(cybersecurity)", "cse(cyber_security)") or clean.lower() in (
        "cse(cs)", "cse (cs)", "cse-cs", "cyber security", "cybersecurity", "cse cyber security"
    ):
        return "CSE(CS)"

    # 4. Standard campus branches
    standard_map = {
        "cse": "CSE",
        "computer science": "CSE",
        "computer science & engineering": "CSE",
        "computer science and engineering": "CSE",
        "ise": "ISE",
        "information science": "ISE",
        "information science & engineering": "ISE",
        "information science and engineering": "ISE",
        "ece": "ECE",
        "electronics & communication engineering": "ECE",
        "electronics and communication engineering": "ECE",
        "eee": "EEE",
        "electrical & electronics engineering": "EEE",
        "electrical and electronics engineering": "EEE",
        "me": "ME",
        "mech": "ME",
        "mechanical": "ME",
        "mechanical engineering": "ME",
        "ce": "CE",
        "civil": "CE",
        "civil engineering": "CE",
        "cv": "CE",
        "aids": "AIDS",
        "ai data science": "AIDS",
        "artificial intelligence & data science": "AIDS",
        "artificial intelligence and data science": "AIDS",
        "bt": "BT",
        "biotech": "BT",
        "biotechnology": "BT",
        "che": "CHE",
        "chemical": "CHE",
        "chemical engineering": "CHE",
        "eie": "EIE",
        "electronics & instrumentation engineering": "EIE",
        "ete": "ETE",
        "telecom": "ETE",
        "telecommunication engineering": "ETE",
        "iem": "IEM",
        "industrial engineering & management": "IEM",
        "ae": "AE",
        "aero": "AE",
        "aerospace": "AE",
        "aerospace engineering": "AE",
        "mle": "MLE",
        "medical electronics": "MLE",
        "b-arch": "B-Arch",
        "architecture": "B-Arch",
        "mca": "MCA",
        "mba": "MBA",
    }
    low = clean.lower()
    if low in standard_map:
        return standard_map[low]
    if norm in standard_map:
        return standard_map[norm]

    if len(clean) <= 5 and clean.isalpha():
        return clean.upper()

    return clean


def validate_and_normalize_profile_fields(fields: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Validates and normalizes candidate student profile fields.
    Returns:
        (valid_fields_dict, invalid_field_names_list)
    Guarantees:
        - Only valid, non-null, supported fields are returned in valid_fields_dict.
        - Invalid or unparseable values (e.g. cgpa="abc", semester=25) are rejected and noted in invalid_fields.
    """
    valid_fields: Dict[str, Any] = {}
    invalid_fields: List[str] = []

    for k, v in fields.items():
        if k not in ALLOWED_PROFILE_FIELDS or v is None:
            continue

        if k == "name":
            clean_name = str(v).strip(' .,;:-')
            if len(clean_name) >= 2 and clean_name.lower() not in {"not specified", "a", "an", "the", "msrit"}:
                valid_fields["name"] = clean_name
            else:
                invalid_fields.append("name")

        elif k == "branch":
            clean_str = str(v).strip()
            if clean_str:
                valid_fields["branch"] = normalize_canonical_branch(clean_str)
            else:
                invalid_fields.append("branch")

        elif k in ("college", "degree", "stream", "cycle"):
            clean_str = str(v).strip()
            if clean_str:
                valid_fields[k] = clean_str
            else:
                invalid_fields.append(k)

        elif k == "semester":
            try:
                sem_int = int(v)
                if 1 <= sem_int <= 10:
                    valid_fields["semester"] = sem_int
                else:
                    invalid_fields.append("semester")
            except (ValueError, TypeError):
                invalid_fields.append("semester")

        elif k == "year":
            try:
                yr_int = int(v)
                if 1 <= yr_int <= 6:
                    valid_fields["year"] = yr_int
                else:
                    invalid_fields.append("year")
            except (ValueError, TypeError):
                invalid_fields.append("year")

        elif k == "cgpa":
            try:
                cgpa_flt = float(v)
                if 0.0 <= cgpa_flt <= 10.0:
                    valid_fields["cgpa"] = round(cgpa_flt, 2)
                else:
                    invalid_fields.append("cgpa")
            except (ValueError, TypeError):
                invalid_fields.append("cgpa")

        elif k == "preferences":
            if v == {} or v == "{}" or v == "null" or v is None:
                valid_fields["preferences"] = {}
            elif isinstance(v, (dict, str)):
                norm_prefs, inv_keys = validate_and_normalize_preferences(v)
                if inv_keys:
                    invalid_fields.extend(inv_keys)
                if norm_prefs or (not inv_keys and isinstance(v, dict)):
                    valid_fields["preferences"] = norm_prefs
            else:
                invalid_fields.append("preferences")

    return valid_fields, invalid_fields


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
    Upsert student profile record. Only updates fields that were explicitly passed and valid (PATCH behavior).
    Preserves all existing unmentioned fields in the record.
    Never overwrites existing database values with NULL.
    Always updates the updated_at timestamp.
    Returns the resulting profile row as a dictionary.
    """
    if not student_id or not student_id.strip():
        return {}

    try:
        clean_id = student_id.strip()
        filtered_fields, _ = validate_and_normalize_profile_fields(fields)

        # Merge preferences if updating partially and not clearing (i.e. not empty dict)
        if "preferences" in filtered_fields:
            if filtered_fields["preferences"] != {}:
                existing_prof = get_student_profile(clean_id)
                if existing_prof and isinstance(existing_prof.get("preferences"), dict):
                    merged_prefs = existing_prof["preferences"].copy()
                    merged_prefs.update(filtered_fields["preferences"])
                    filtered_fields["preferences"] = merged_prefs

        # If no valid profile fields passed, check if record exists or just update updated_at
        columns = ["student_id"]
        placeholders = ["%s"]
        values: List[Any] = [clean_id]
        update_clauses = []

        for col, val in filtered_fields.items():
            columns.append(col)
            placeholders.append("%s")
            if col == "preferences" and isinstance(val, (dict, list)):
                values.append(psycopg2.extras.Json(val))
            else:
                values.append(val)
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


def delete_student_profile(student_id: str) -> bool:
    """
    Deletes a student profile from PostgreSQL.
    Useful for test cleanup and isolation.
    """
    if not student_id or not student_id.strip():
        return False
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM student_profile WHERE student_id = %s;", (student_id.strip(),))
        conn.commit()
        deleted = cur.rowcount > 0
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        print(f"Error in delete_student_profile: {e}", file=sys.stderr)
        return False


def format_preferences_response(preferences: Optional[Dict[str, Any]], field: str = "preferences") -> str:
    """
    Deterministically formats saved student preferences.
    Only states verified preferences, and clearly reports when none exist.
    """
    if not preferences or not isinstance(preferences, dict) or not preferences:
        if field == "explanation_style":
            return "You haven't set an explanation style preference yet."
        if field == "focus_subject":
            return "You haven't set a focus subject yet."
        return "You don't have any saved preferences yet."

    if field == "explanation_style":
        style = preferences.get("explanation_style")
        if style:
            return f"You prefer {style} explanations."
        return "You haven't set an explanation style preference yet."

    if field == "focus_subject":
        subj = preferences.get("focus_subject")
        if subj:
            return f"Your saved focus subject is {subj}."
        return "You haven't set a focus subject yet."

    lines = ["**Your Saved Preferences:**"]
    if "explanation_style" in preferences:
        lines.append(f"- **Explanation Style:** {preferences['explanation_style'].capitalize()} explanations")
    if "focus_subject" in preferences:
        lines.append(f"- **Focus Subject:** {preferences['focus_subject']}")

    if len(lines) == 1:
        return "You don't have any saved preferences yet."

    return "\n".join(lines)


def format_single_field_response(profile: Optional[Dict[str, Any]], field: str) -> str:
    """
    Formats a single-field response deterministically without dumping the whole profile.
    Only states verified facts, and clearly states if unrecorded.
    """
    if not profile:
        profile = {}

    if field in ("preferences", "explanation_style", "focus_subject"):
        prefs = profile.get("preferences")
        return format_preferences_response(prefs, field)

    if field == "name":
        val = profile.get("name")
        return f"Your name is {val}." if val else "I haven't recorded your name in your profile yet."

    if field == "cgpa":
        val = profile.get("cgpa")
        return f"Your recorded CGPA is {val}." if val is not None else "I haven't recorded your CGPA yet."

    if field == "branch":
        val = profile.get("branch")
        return f"You are in the {val} branch." if val else "I haven't recorded your branch yet."

    if field == "semester":
        val = profile.get("semester")
        return f"You are currently in semester {val}." if val is not None else "I haven't recorded your semester yet."

    if field == "year":
        val = profile.get("year")
        return f"You are currently in year {val}." if val is not None else "I haven't recorded your academic year yet."

    if field == "college":
        val = profile.get("college")
        return f"You study at {val}." if val else "I haven't recorded your college in your profile yet."

    if field == "degree":
        deg = profile.get("degree")
        br = profile.get("branch")
        if deg and br:
            return f"You are pursuing {deg} in {br}."
        elif deg:
            return f"You are pursuing {deg}."
        elif br:
            return f"You are in the {br} branch."
        return "I haven't recorded your degree or program yet."

    return "I do not have that profile field recorded yet."


def format_profile_overview(profile: Optional[Dict[str, Any]], student_id: str) -> str:
    """
    Formats full profile response.
    Synthesizes conversational summary grounded strictly in available facts,
    followed by verified profile facts card.
    """
    if not profile or not any(profile.get(k) is not None for k in [
        "name", "college", "degree", "branch", "semester", "year", "stream", "cycle", "cgpa", "preferences"
    ]):
        return (
            "You haven't set your profile yet. You can tell me something like "
            "'My name is Vishal and I am in 3rd semester CSE' to set it up!"
        )

    name = profile.get("name")
    college = profile.get("college")
    degree = profile.get("degree")
    branch = profile.get("branch")
    semester = profile.get("semester")
    cgpa = profile.get("cgpa")

    # Construct natural introductory sentences using ONLY known facts
    intro_parts = []
    if name:
        if degree and college and branch:
            intro_parts.append(f"You are {name}, a {degree} student at {college} in the {branch} branch.")
        elif degree and college:
            intro_parts.append(f"You are {name}, a {degree} student at {college}.")
        elif college and branch:
            intro_parts.append(f"You are {name}, studying at {college} in {branch}.")
        elif branch:
            intro_parts.append(f"You are {name} in the {branch} branch.")
        else:
            intro_parts.append(f"Your name is {name}.")
    else:
        if degree and college and branch:
            intro_parts.append(f"You are a {degree} student at {college} in the {branch} branch.")
        elif branch:
            intro_parts.append(f"You are in the {branch} branch.")

    acad_parts = []
    if semester is not None and cgpa is not None:
        acad_parts.append(f"You are currently in semester {semester}, and your recorded CGPA is {cgpa}.")
    elif semester is not None:
        acad_parts.append(f"You are currently in semester {semester}.")
    elif cgpa is not None:
        acad_parts.append(f"Your recorded CGPA is {cgpa}.")

    summary_text = " ".join(intro_parts + acad_parts).strip()

    field_labels = [
        ("name", "Name"),
        ("college", "College"),
        ("degree", "Degree"),
        ("branch", "Branch"),
        ("semester", "Semester"),
        ("year", "Year"),
        ("stream", "Stream"),
        ("cycle", "Cycle"),
        ("cgpa", "CGPA"),
    ]
    lines = []
    if summary_text:
        lines.append(summary_text)
        lines.append("")
    lines.append(f"**Your Student Profile ({student_id}):**")
    for key, label in field_labels:
        val = profile.get(key)
        if val is not None and str(val).strip():
            lines.append(f"- **{label}:** {val}")

    prefs = profile.get("preferences")
    if prefs and isinstance(prefs, dict):
        if "explanation_style" in prefs:
            lines.append(f"- **Explanation Style:** {prefs['explanation_style'].capitalize()} explanations")
        if "focus_subject" in prefs:
            lines.append(f"- **Focus Subject:** {prefs['focus_subject']}")

    return "\n".join(lines)

