"""
Academic Document Retrieval module for MSRIT AI.
Provides deterministic search and metadata retrieval for local MSRIT course documents,
notes, question papers, lab manuals, and syllabus files.
"""
from typing import Optional, List, Dict, Any, Tuple
import os
import re
import sys
import json
from pathlib import Path
from db.connection import get_connection

BASE_DIR = Path(__file__).resolve().parent.parent

# Canonical subject mappings and aliases
SUBJECT_ALIASES = {
    # Mathematics
    "maths": "Mathematics",
    "math": "Mathematics",
    "mathematics": "Mathematics",
    "calculus": "Mathematics",
    "differential calculus": "Mathematics",
    "linear algebra": "Mathematics",
    "laplace": "Mathematics",
    "laplace transform": "Mathematics",
    "mac11": "Mathematics",
    "mac21": "Mathematics",
    "m1": "Mathematics",
    "m2": "Mathematics",
    # Physics
    "physics": "Physics",
    "phy": "Physics",
    "applied physics": "Physics",
    "engineering physics": "Physics",
    "quantum mechanics": "Physics",
    "elasticity": "Physics",
    "cryogenics": "Physics",
    # Chemistry
    "chemistry": "Chemistry",
    "chem": "Chemistry",
    "applied chemistry": "Chemistry",
    "engineering chemistry": "Chemistry",
    "corrosion": "Chemistry",
    # C Programming
    "c programming": "Programming in C",
    "programming in c": "Programming in C",
    "c prog": "Programming in C",
    "cprog": "Programming in C",
    "c language": "Programming in C",
    "c": "Programming in C",
    "c pointer": "Programming in C",
    "pointers in c": "Programming in C",
    # Civil
    "civil engineering": "Civil Engineering (ESC)",
    "civil": "Civil Engineering (ESC)",
    "elements of civil engineering": "Civil Engineering (ESC)",
    # Mechanical
    "mechanical engineering": "Mechanical Engineering (ESC)",
    "mechanical": "Mechanical Engineering (ESC)",
    "elements of mechanical engineering": "Mechanical Engineering (ESC)",
}

# Document types
DOC_TYPE_ALIASES = {
    "notes": "notes",
    "note": "notes",
    "lecture notes": "notes",
    "handwritten notes": "notes",
    "unit notes": "notes",
    "pdf": "notes",  # Default if user asks for PDF/notes
    "question paper": "question_paper",
    "question papers": "question_paper",
    "pyq": "question_paper",
    "pyqs": "question_paper",
    "previous year paper": "question_paper",
    "previous year papers": "question_paper",
    "previous year question paper": "question_paper",
    "cie": "question_paper",
    "cie paper": "question_paper",
    "cie 1": "question_paper",
    "cie 2": "question_paper",
    "lab manual": "lab_manual",
    "lab record": "lab_manual",
    "laboratory manual": "lab_manual",
    "lab": "lab_manual",
    "syllabus": "syllabus",
    "curriculum": "syllabus",
    "study material": "study_material",
    "textbook": "study_material",
    "book": "study_material",
    "practice problems": "study_material",
    "tutorials": "study_material",
    "tutorial": "study_material",
    "question bank": "study_material"
}


def normalize_subject(text: str) -> Optional[str]:
    """Match subject aliases in text, longest first."""
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', text.lower()).strip()
    
    # Check exact aliases first
    if clean in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[clean]
        
    for alias in sorted(SUBJECT_ALIASES.keys(), key=len, reverse=True):
        # Avoid matching single-letter 'c' inside normal words
        if alias == "c":
            pat = r'\b(?:programming\s+in\s+c|c\s+programming|c\s+code|c\s+language|in\s+c)\b'
            if re.search(pat, clean):
                return "Programming in C"
            continue
        pat = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
        if re.search(pat, clean):
            return SUBJECT_ALIASES[alias]
    return None


def detect_document_query_params(query: str) -> Dict[str, Any]:
    """
    Extracts structured document parameters from a user query:
    subject, unit, document_type, year, title_keyword, needs_subject_clarification, needs_type_clarification.
    """
    clean = query.strip()
    lower = clean.lower()

    params: Dict[str, Any] = {
        "raw_query": clean,
        "subject": None,
        "unit": None,
        "document_type": None,
        "year": None,
        "title_keyword": None,
        "needs_subject_clarification": False,
        "needs_type_clarification": False
    }

    # 1. Subject extraction
    subj = normalize_subject(lower)
    params["subject"] = subj

    # 2. Unit extraction: e.g. "unit 1", "unit 2", "unit_1", "unit-3", "unit i", "unit ii"
    unit_m = re.search(r'\bunit\s*[-_]?\s*(\d+|i{1,3}|iv|v)\b', lower)
    if unit_m:
        raw_u = unit_m.group(1).lower()
        roman_map = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
        if raw_u.isdigit():
            params["unit"] = int(raw_u)
        elif raw_u in roman_map:
            params["unit"] = roman_map[raw_u]

    # 3. Document Type extraction
    for dt_alias in sorted(DOC_TYPE_ALIASES.keys(), key=len, reverse=True):
        if dt_alias == "pdf":
            # Only match PDF if other specific types are not present
            continue
        pat = r'(?<![a-zA-Z0-9])' + re.escape(dt_alias) + r'(?![a-zA-Z0-9])'
        if re.search(pat, lower):
            params["document_type"] = DOC_TYPE_ALIASES[dt_alias]
            break

    # If document_type still None and 'pdf' or 'document' or 'notes' is mentioned
    if not params["document_type"]:
        if re.search(r'\b(?:notes?|pdf|file|document)\b', lower):
            params["document_type"] = "notes"

    # 4. Exam year extraction (e.g. 2023, 2024, 2025)
    yr_m = re.search(r'\b(20\d\d)\b', lower)
    if yr_m:
        params["year"] = yr_m.group(1)

    # 5. Topic / Title keyword check (e.g. "Laplace", "Laplace Transform", "Corrosion", "Elasticity")
    for topic in ["laplace transform", "laplace", "corrosion", "elasticity", "quantum mechanics", "differential calculus"]:
        if topic in lower:
            params["title_keyword"] = topic
            if not params["subject"]:
                params["subject"] = normalize_subject(topic)

    # 6. Ambiguity checks
    # Ambiguity Case A: User specifies unit without specifying subject
    # Example: "Give me Unit 2", "Show me Unit 3 notes"
    if params["unit"] is not None and not params["subject"]:
        params["needs_subject_clarification"] = True

    # Ambiguity Case B: Generic query like "Give me the maths PDF" without unit or doc_type specification
    # User just said "maths pdf" or "maths document", which could be notes, question papers, syllabus, or lab manual
    is_very_generic_pdf = bool(re.search(r'\b(?:the\s+)?(?:maths?|physics|chemistry|c\s+programming)\s+(?:pdf|document|file)\b', lower))
    has_no_unit_or_specific_type = (params["unit"] is None and (not params["document_type"] or params["document_type"] == "notes") and not params["year"] and not params["title_keyword"])
    if is_very_generic_pdf and has_no_unit_or_specific_type and "notes" not in lower:
        params["needs_type_clarification"] = True

    return params


def search_academic_documents(
    query: Optional[str] = None,
    subject: Optional[str] = None,
    unit: Optional[int] = None,
    semester: Optional[int] = None,
    branch: Optional[str] = None,
    document_type: Optional[str] = None,
    year: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search academic_documents with deterministic metadata filtering.
    Prioritizes exact metadata filters before substring title matches.
    Verifies local file availability on disk.
    """
    try:
        where_clauses = []
        params = []

        if subject and subject.strip():
            sub_val = subject.strip()
            where_clauses.append("(subject ILIKE %s OR subject ILIKE %s)")
            params.extend([sub_val, f"%{sub_val}%"])

        if unit is not None:
            where_clauses.append("unit = %s")
            params.append(unit)

        if semester is not None:
            where_clauses.append("semester = %s")
            params.append(semester)

        if branch and branch.strip():
            b_val = branch.strip()
            where_clauses.append("(branch ILIKE %s OR branch IS NULL)")
            params.append(f"%{b_val}%")

        if document_type and document_type.strip():
            dt_val = document_type.strip()
            # If notes is requested, also match study_material if no exact notes found
            where_clauses.append("document_type ILIKE %s")
            params.append(f"%{dt_val}%")

        if year and year.strip():
            y_val = year.strip()
            where_clauses.append("(year ILIKE %s OR title ILIKE %s)")
            params.extend([f"%{y_val}%", f"%{y_val}%"])

        if query and query.strip():
            q_clean = query.strip()
            where_clauses.append("(title ILIKE %s OR subject ILIKE %s OR local_file_path ILIKE %s)")
            params.extend([f"%{q_clean}%", f"%{q_clean}%", f"%{q_clean}%"])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT 
                document_id, title, subject, semester, branch, 
                stream, cycle, unit, document_type, year, 
                source_url, local_file_path
            FROM academic_documents
            {where_sql}
            ORDER BY unit ASC NULLS LAST, title ASC
            LIMIT %s;
        """

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql, params + [limit])
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for r in rows:
            doc_id, title, subj, sem, br, st, cy, u, dt, yr, src_url, fp = r
            
            # Check local file existence on disk
            full_fp = BASE_DIR / fp if fp else None
            is_local = full_fp.exists() if full_fp else False

            results.append({
                "document_id": doc_id,
                "title": title,
                "subject": subj,
                "semester": sem,
                "branch": br,
                "stream": st,
                "cycle": cy,
                "unit": u,
                "document_type": dt,
                "year": yr,
                "source_url": src_url or "",
                "local_file_path": fp or "",
                "is_local": is_local
            })

        return results

    except Exception as e:
        print(f"Error in search_academic_documents: {e}", file=sys.stderr)
        return []


def get_academic_document(document_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single verified academic document by ID."""
    if not document_id or not document_id.strip():
        return None

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                document_id, title, subject, semester, branch, 
                stream, cycle, unit, document_type, year, 
                source_url, local_file_path
            FROM academic_documents
            WHERE document_id = %s;
        """, (document_id.strip(),))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        doc_id, title, subj, sem, br, st, cy, u, dt, yr, src_url, fp = row
        full_fp = BASE_DIR / fp if fp else None
        is_local = full_fp.exists() if full_fp else False

        return {
            "document_id": doc_id,
            "title": title,
            "subject": subj,
            "semester": sem,
            "branch": br,
            "stream": st,
            "cycle": cy,
            "unit": u,
            "document_type": dt,
            "year": yr,
            "source_url": src_url or "",
            "local_file_path": fp or "",
            "is_local": is_local
        }
    except Exception as e:
        print(f"Error in get_academic_document: {e}", file=sys.stderr)
        return None


def format_document_response(
    docs: List[Dict[str, Any]],
    query_params: Dict[str, Any]
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Formats the document search results into a clean, concise, helpful markdown message.
    Returns (markdown_text, sources_list).
    """
    sources = []
    for d in docs:
        if d.get("local_file_path"):
            sources.append({
                "file_path": d["local_file_path"],
                "subject": d.get("subject", "Course Document"),
                "source_url": d.get("source_url", "")
            })

    if not docs:
        subj = query_params.get("subject")
        unit = query_params.get("unit")
        unit_str = f" Unit {unit}" if unit is not None else ""
        item_str = f"{subj}{unit_str}" if subj else "requested"
        answer = f"The requested {item_str} document is not currently available in the local MSRIT knowledge base."
        return answer, []

    type_label_map = {
        "notes": "Notes",
        "question_paper": "Question Paper / PYQ",
        "lab_manual": "Lab Manual",
        "syllabus": "Syllabus",
        "study_material": "Study Material"
    }

    # Case 1: Exact single document match
    if len(docs) == 1:
        d = docs[0]
        dt_label = type_label_map.get(d["document_type"], d["document_type"].title())
        unit_str = f" Unit {d['unit']}" if d.get("unit") is not None else ""
        year_str = f" ({d['year']})" if d.get("year") else ""
        
        lines = [
            f"I found the **{d['subject']}{unit_str} {dt_label}{year_str}**:",
            f"- **Title:** {d['title']}",
            f"- **Subject:** {d['subject']}",
            f"- **Type:** {dt_label}",
        ]
        if d.get("unit") is not None:
            lines.append(f"- **Unit:** Unit {d['unit']}")
        if d.get("local_file_path"):
            lines.append(f"- **Local File:** `{d['local_file_path']}`")
        if d.get("source_url"):
            lines.append(f"- **Source:** [RITNotebook Cloud Link]({d['source_url']})")

        return "\n".join(lines), sources

    # Case 2: Multiple matching documents found
    subj = query_params.get("subject") or docs[0].get("subject", "Course")
    unit = query_params.get("unit")
    unit_str = f" Unit {unit}" if unit is not None else ""

    lines = [f"I found these **{len(docs)} {subj}{unit_str}** documents:"]
    for i, d in enumerate(docs[:6], 1):
        dt_label = type_label_map.get(d["document_type"], d["document_type"].title())
        u_str = f" | Unit {d['unit']}" if d.get("unit") is not None else ""
        yr_str = f" | {d['year']}" if d.get("year") else ""
        lines.append(f"{i}. **{d['title']}** [{dt_label}{u_str}{yr_str}] - `{d['local_file_path']}`")

    if len(docs) > 6:
        lines.append(f"\n*(and {len(docs) - 6} more)*")

    lines.append("\nWhich one would you like to access?")
    return "\n".join(lines), sources
