"""
Knowledge / Relationship Layer module for MSRIT AI.
Provides deterministic resolution of relationships connecting:
  Student -> Branch -> Curricular Stream -> Cycle -> Subjects -> Documents -> Units
and:
  Student -> Branch -> Clubs (via branch_scope)
Authoritative source of truth: PostgreSQL.
"""
from typing import Optional, List, Dict, Any, Tuple
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.connection import get_connection
from backend.memory import (
    get_student_profile,
    normalize_canonical_branch
)
from backend.info_lookup import (
    BRANCH_ALIASES,
    find_branch_code,
    lookup_branch
)


def resolve_branch_db_code(raw_branch: Optional[str]) -> Optional[str]:
    """
    Resolves branch name or query into the exact primary key code used in branches table.
    Crucial guarantee:
      - 'AI&ML' -> 'AI&ML'
      - 'CSE(AI&ML)' / 'CSE-AIML' -> 'CSE(AIML)'
      - 'CSE' -> 'CSE'
      - Preserves strict distinction between AI&ML and CSE(AI&ML).
    """
    if not raw_branch or not str(raw_branch).strip():
        return None

    clean = str(raw_branch).strip()
    norm = normalize_canonical_branch(clean)

    # Database table branches.code uses 'CSE(AIML)' for CSE AIML
    if norm in ("CSE(AI&ML)", "CSE(AIML)"):
        return "CSE(AIML)"
    if norm == "AI&ML":
        return "AI&ML"
    if norm in ("CSE(CS)", "CSE-CS"):
        return "CSE(CS)"

    # Check info_lookup aliases
    matched_code = find_branch_code(clean)
    if matched_code:
        if matched_code == "CSE(AIML)":
            return "CSE(AIML)"
        return matched_code

    return norm


def get_academic_context(
    student_id: Optional[str] = None,
    branch: Optional[str] = None,
    cycle: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolves multi-hop academic curriculum relationships:
    Student -> Branch -> Department Info -> Curricular Stream -> Cycle -> Subjects -> Academic Documents.
    
    If student_id is provided, loads the verified profile without inferring unsupported fields.
    If branch is provided, normalizes deterministically.
    Returns structured data for grounded reasoning.
    """
    result: Dict[str, Any] = {
        "student_id": student_id,
        "branch": None,
        "branch_code": None,
        "department": None,
        "stream": None,
        "cycle": None,
        "subjects": [],
        "total_documents": 0,
        "error": None
    }

    resolved_branch = branch
    resolved_cycle = cycle

    # 1. If student_id is provided, retrieve verified student profile
    if student_id and str(student_id).strip():
        try:
            profile = get_student_profile(student_id.strip())
            if profile:
                result["student_name"] = profile.get("name")
                result["semester"] = profile.get("semester")
                if not resolved_branch and profile.get("branch"):
                    resolved_branch = profile.get("branch")
                if not resolved_cycle and profile.get("cycle"):
                    resolved_cycle = profile.get("cycle")
                if profile.get("stream"):
                    result["profile_stream"] = profile.get("stream")
        except Exception as e:
            print(f"Warning: Failed to load profile in get_academic_context: {e}", file=sys.stderr)

    if not resolved_branch or not str(resolved_branch).strip():
        result["error"] = "No branch specified or recorded in student profile."
        return result

    # 2. Resolve canonical branch code
    db_branch_code = resolve_branch_db_code(resolved_branch)
    result["branch_code"] = db_branch_code
    result["branch"] = "CSE(AI&ML)" if db_branch_code == "CSE(AIML)" else (db_branch_code or resolved_branch)

    # Normalize cycle filter if provided
    if resolved_cycle and str(resolved_cycle).strip():
        c_low = str(resolved_cycle).lower()
        if "phys" in c_low:
            result["cycle"] = "Physics Cycle"
        elif "chem" in c_low:
            result["cycle"] = "Chemistry Cycle"

    try:
        conn = get_connection()
        cur = conn.cursor()

        # 3. Retrieve Department details (HOD, location, official name)
        cur.execute(
            """
            SELECT code, name, stream, hod_name, location
            FROM branches
            WHERE code = %s OR code ILIKE %s
            LIMIT 1;
            """,
            (db_branch_code, db_branch_code)
        )
        b_row = cur.fetchone()
        if b_row:
            result["department"] = {
                "code": b_row[0],
                "name": b_row[1],
                "discipline_stream": b_row[2],
                "hod_name": b_row[3],
                "location": b_row[4]
            }

        # 4. Resolve First-Year Curricular Stream via stream_branches
        cur.execute(
            """
            SELECT stream_name
            FROM stream_branches
            WHERE branch_code = %s
            LIMIT 1;
            """,
            (db_branch_code,)
        )
        sb_row = cur.fetchone()
        if not sb_row:
            # Branch exists, but is outside the 4 First-Year engineering streams (e.g. Architecture)
            cur.close()
            conn.close()
            result["error"] = (
                f"Branch '{resolved_branch}' ({db_branch_code}) is not enrolled in the First-Year "
                f"engineering curricular streams (Physics/Chemistry cycle)."
            )
            return result

        curricular_stream = sb_row[0]
        result["stream"] = curricular_stream

        # 5. Resolve Subjects and document statistics
        where_clauses = ["ss.stream_name = %s"]
        params: List[Any] = [curricular_stream]

        if result["cycle"]:
            where_clauses.append("ss.cycle = %s")
            params.append(result["cycle"])

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT 
                s.code,
                s.name,
                ss.cycle,
                COUNT(d.id) AS doc_count,
                ARRAY_AGG(DISTINCT d.unit ORDER BY d.unit) FILTER (WHERE d.unit IS NOT NULL) AS units,
                ARRAY_AGG(DISTINCT d.document_type ORDER BY d.document_type) FILTER (WHERE d.document_type IS NOT NULL) AS doc_types
            FROM stream_subjects ss
            JOIN subjects s ON ss.subject_code = s.code
            LEFT JOIN academic_documents d ON (
                d.subject = s.name 
                AND (d.cycle ILIKE '%%' || ss.cycle || '%%' OR d.cycle IS NULL)
                AND (d.stream ILIKE '%%' || ss.stream_name || '%%' OR d.stream IS NULL)
            )
            WHERE {where_sql}
            GROUP BY s.code, s.name, ss.cycle
            ORDER BY ss.cycle, s.name;
        """

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        subjects_list = []
        tot_docs = 0
        for r in rows:
            s_code, s_name, s_cycle, d_cnt, units, doc_types = r
            tot_docs += (d_cnt or 0)
            subjects_list.append({
                "code": s_code,
                "name": s_name,
                "cycle": s_cycle,
                "document_count": d_cnt or 0,
                "units": units or [],
                "document_types": doc_types or []
            })

        result["subjects"] = subjects_list
        result["total_documents"] = tot_docs
        return result

    except Exception as e:
        print(f"Error in get_academic_context: {e}", file=sys.stderr)
        result["error"] = f"Database query failed: {e}"
        return result


def get_recommended_clubs(
    branch: Optional[str] = None,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search and filter clubs based on student branch scope and optional category.
    Rules:
      - 'All branches' clubs match every student.
      - Branch-specific clubs match when the student's branch code or discipline appears in branch_scope.
      - Category filtering is deterministic.
      - No artificial ranking or invented suitability.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT id, name, category, lead_name, description, branch_scope FROM clubs ORDER BY name ASC;")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        clean_branch = None
        db_code = None
        if branch and str(branch).strip():
            db_code = resolve_branch_db_code(branch.strip())
            clean_branch = db_code or branch.strip().upper()

        matching_clubs = []
        for r in rows:
            c_id, name, cat, lead, desc, scope = r
            scope_str = scope or "All branches"

            # 1. Category check
            if category and str(category).strip():
                if str(category).strip().lower() not in (cat or "").lower():
                    continue

            # 2. Branch check
            if not clean_branch:
                # If no branch specified, return all matching the category
                matching_clubs.append({
                    "id": c_id,
                    "name": name,
                    "category": cat,
                    "lead_name": lead,
                    "description": desc,
                    "branch_scope": scope_str
                })
                continue

            # If branch is specified:
            # Matches if scope is "All branches"
            is_match = False
            scope_low = scope_str.lower()
            if "all branches" in scope_low:
                is_match = True
            elif clean_branch:
                # Direct code check (e.g. 'CSE', 'ME', 'ECE')
                pat = r'(?<![a-zA-Z0-9])' + re.escape(clean_branch.lower()) + r'(?![a-zA-Z0-9])'
                if re.search(pat, scope_low):
                    is_match = True
                # Check branch full name or common keywords
                elif clean_branch == "ME" and "mechanical" in scope_low:
                    is_match = True
                elif clean_branch in ("CSE", "ISE", "AI&ML", "CSE(AIML)", "AIDS", "CSE(CS)") and "cse" in scope_low:
                    is_match = True
                elif clean_branch == "AI&ML" and ("aiml" in scope_low or "ai" in scope_low):
                    is_match = True
                elif clean_branch == "CSE(AIML)" and ("aiml" in scope_low or "cse" in scope_low):
                    is_match = True
                elif clean_branch == "CSE(CS)" and ("cyber" in scope_low or "security" in scope_low):
                    is_match = True
                elif clean_branch == "CHE" and "chemical" in scope_low:
                    is_match = True
                elif clean_branch == "CE" and "civil" in scope_low:
                    is_match = True
                elif clean_branch == "AE" and "aerospace" in scope_low:
                    is_match = True

            if is_match:
                matching_clubs.append({
                    "id": c_id,
                    "name": name,
                    "category": cat,
                    "lead_name": lead,
                    "description": desc,
                    "branch_scope": scope_str
                })

        return matching_clubs

    except Exception as e:
        print(f"Error in get_recommended_clubs: {e}", file=sys.stderr)
        return []


def format_academic_context_response(context: Dict[str, Any]) -> str:
    """
    Formats the structured academic context into a clear, grounded response.
    """
    if context.get("error"):
        return f"Unable to resolve academic curriculum: {context['error']}"

    branch_display = context.get("branch") or "your branch"
    stream = context.get("stream", "First-Year Stream")
    cycle = context.get("cycle")
    cycle_str = f" ({cycle})" if cycle else ""
    dept = context.get("department")

    lines = [f"**Academic Curriculum & Resources for {branch_display}{cycle_str}:**"]
    lines.append(f"- **Curricular Stream:** {stream}")
    if dept:
        lines.append(f"- **Department:** {dept.get('name')} | HOD: {dept.get('hod_name')} | Office: {dept.get('location')}")

    subjects = context.get("subjects", [])
    if not subjects:
        lines.append("\nNo specific subjects found for this semester or cycle.")
        return "\n".join(lines)

    lines.append(f"\n**Enrolled Subjects ({len(subjects)}):**")
    for s in subjects:
        u_str = f" [Units {', '.join(str(u) for u in s['units'])}]" if s['units'] else ""
        d_cnt = s.get("document_count", 0)
        docs_str = f" — {d_cnt} verified document{'s' if d_cnt != 1 else ''}"
        lines.append(f"- **{s['name']}** ({s['cycle']}){u_str}{docs_str}")

    return "\n".join(lines)


def format_recommended_clubs_response(
    clubs: List[Dict[str, Any]],
    branch: Optional[str] = None
) -> str:
    """
    Formats the recommended clubs response grounded strictly in database facts.
    """
    if not clubs:
        target = f" for {branch}" if branch else ""
        return f"No clubs found matching the criteria{target}."

    target_str = f" for **{branch}**" if branch else ""
    lines = [f"I found **{len(clubs)} clubs** available{target_str}:"]

    # Group by category
    categories: Dict[str, List[Dict[str, Any]]] = {}
    for c in clubs:
        cat = c.get("category", "General")
        categories.setdefault(cat, []).append(c)

    for cat, items in sorted(categories.items()):
        lines.append(f"\n**{cat} Clubs:**")
        for item in items:
            desc = item.get("description") or ""
            lead = item.get("lead_name")
            lead_str = f" (Lead: {lead})" if lead else ""
            scope = item.get("branch_scope", "All branches")
            lines.append(f"- **{item['name']}**{lead_str}: {desc} *(Eligibility: {scope})*")

    return "\n".join(lines)
