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

    # 5. Topic / Title keyword check (e.g. "Lasers", "May", "Laplace", "Corrosion", "Elasticity")
    KNOWN_TOPICS = [
        ("laplace transform", "laplace transform"),
        ("laplace", "laplace"),
        ("differential calculus", "differential calculus"),
        ("quantum mechanics", "quantum mechanics"),
        ("optical fibres", "optical fibres"),
        ("optical fibers", "optical fibers"),
        ("optical fiber", "optical fiber"),
        ("lasers", "lasers"),
        ("laser", "laser"),
        ("electrochemistry", "electrochemistry"),
        ("corrosion", "corrosion"),
        ("polymer and liquid crystal", "polymer"),
        ("polymer", "polymer"),
        ("liquid crystal", "liquid crystal"),
        ("fuel cells", "fuel cells"),
        ("materials science", "materials science"),
        ("semiconductors", "semiconductor"),
        ("semiconductor", "semiconductor"),
        ("quantum computing", "quantum computing"),
        ("cryogenics", "cryogenics"),
        ("dielectrics", "dielectrics"),
        ("modern physics", "modern physics"),
        ("vibrations", "vibrations"),
        ("elasticity", "elasticity"),
        ("electrical conductivity", "electrical conductivity"),
        ("2023 may", "may"),
        ("2023 sept", "sept"),
        ("2023 september", "sept"),
        ("may", "may"),
        ("september", "sept"),
        ("sept", "sept"),
        ("cie 1 chem", "cie 1 chem"),
        ("cie 2 chem", "cie 2 chem"),
        ("cie 2 phy", "cie 2 phy"),
        ("cie 1", "cie 1"),
        ("cie 2", "cie 2"),
        ("cprog", "cprog"),
        ("concise", "concise")
    ]
    for topic, search_term in KNOWN_TOPICS:
        pat = r'(?<![a-zA-Z0-9])' + re.escape(topic) + r'(?![a-zA-Z0-9])'
        if re.search(pat, lower):
            params["title_keyword"] = search_term
            if not params["subject"]:
                params["subject"] = normalize_subject(topic)
            break

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
                "source_url": PUBLIC_FIRST_YEAR_URL,
                "public_url": PUBLIC_FIRST_YEAR_URL,
                "file_path": PUBLIC_FIRST_YEAR_URL,
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
            "source_url": PUBLIC_FIRST_YEAR_URL,
            "public_url": PUBLIC_FIRST_YEAR_URL,
            "file_path": PUBLIC_FIRST_YEAR_URL,
            "local_file_path": fp or "",
            "is_local": is_local
        }
    except Exception as e:
        print(f"Error in get_academic_document: {e}", file=sys.stderr)
        return None


PUBLIC_FIRST_YEAR_URL = "https://ritnotebook.pages.dev/notes/first"


def sanitize_document_metadata(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize a document dictionary to ensure NO internal filesystem paths,
    local_file_path keys, or internal folder IDs can reach the frontend,
    agentic tool results, or conversation responses.
    """
    if not isinstance(doc, dict):
        return doc

    return {
        "document_id": doc.get("document_id"),
        "title": doc.get("title", ""),
        "subject": doc.get("subject", ""),
        "unit": doc.get("unit"),
        "document_type": doc.get("document_type"),
        "year": doc.get("year"),
        "semester": doc.get("semester"),
        "branch": doc.get("branch"),
        "stream": doc.get("stream"),
        "cycle": doc.get("cycle"),
        "public_url": PUBLIC_FIRST_YEAR_URL,
        "source_url": PUBLIC_FIRST_YEAR_URL,
        "file_path": PUBLIC_FIRST_YEAR_URL,
        "is_local": bool(doc.get("is_local", False))
    }


def sanitize_source(src: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize source card metadata returned to frontend or logged in conversation history.
    Never exposes data/raw, local_file_path, filesystem paths, or folder IDs.
    """
    if not isinstance(src, dict):
        return {}

    title = src.get("title") or src.get("subject") or "First-Year Academic Resources"
    subj = src.get("subject") or "Course Document"

    safe: Dict[str, Any] = {
        "title": title,
        "subject": subj,
        "public_url": PUBLIC_FIRST_YEAR_URL,
        "source_url": PUBLIC_FIRST_YEAR_URL,
        "file_path": PUBLIC_FIRST_YEAR_URL
    }
    if src.get("unit") is not None:
        safe["unit"] = src.get("unit")
    if src.get("document_type"):
        safe["document_type"] = src.get("document_type")
    if src.get("year"):
        safe["year"] = src.get("year")

    return safe


def sanitize_text(text: str) -> str:
    """
    Ensures that strings containing data/raw, local_file_path, or internal folder IDs
    never appear in final user-facing academic responses.
    """
    if not text:
        return text

    # Strip or replace raw directory paths
    cleaned = re.sub(r'data[/\\]raw[/\\][^\s\)\"\'>]+', PUBLIC_FIRST_YEAR_URL, text, flags=re.I)
    cleaned = re.sub(r'local_file_path\s*[:=]\s*[^\s,]+', '', cleaned, flags=re.I)
    cleaned = re.sub(r'__[0-9a-zA-Z_-]{8,}', '', cleaned)
    cleaned = re.sub(r'https?://drive\.google\.com/drive/folders/[0-9a-zA-Z_-]+(?:\?[^\s\)\"\'>]*)?', PUBLIC_FIRST_YEAR_URL, cleaned)
    return cleaned


def format_document_response(
    docs: List[Dict[str, Any]],
    query_params: Dict[str, Any]
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Formats the document search results into a clean, concise, helpful markdown message.
    Never exposes internal filesystem paths or data/raw directories to users.
    Returns (markdown_text, sources_list).
    """
    sources = []
    for d in docs:
        sources.append(sanitize_source(d))

    if not docs:
        subj = query_params.get("subject")
        unit = query_params.get("unit")
        unit_str = f" Unit {unit}" if unit is not None else ""
        item_str = f"{subj}{unit_str}" if subj else "requested"
        answer = f"The requested {item_str} document is not currently available in the local MSRIT knowledge base."
        return sanitize_text(answer), []

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
        dt = d.get("document_type", "notes")
        dt_label = type_label_map.get(dt, dt.title())
        unit_str = f" Unit {d['unit']}" if d.get("unit") is not None else ""
        year_str = f" ({d['year']})" if d.get("year") else ""
        title = d.get("title", "").strip()

        if dt == "question_paper":
            clean_title = title
            if clean_title.lower() == "2023 may":
                clean_title = "2023 May"
            elif clean_title.lower() == "2023 sept":
                clean_title = "2023 September"
            answer = f"Here is the {d['subject']} {clean_title} question paper:\n\n{PUBLIC_FIRST_YEAR_URL}"
        elif d.get("subject", "").lower() == "programming in c" and "cprog" in title.lower():
            answer = f"Here is the Programming in C — {title} notes:\n\n{PUBLIC_FIRST_YEAR_URL}"
        elif unit_str and unit_str.strip().lower() in title.lower():
            answer = f"Here is the {d['subject']} {title} {dt_label.lower()}:\n\n{PUBLIC_FIRST_YEAR_URL}"
        else:
            answer = f"Here is the {d['subject']}{unit_str} ({title}) {dt_label.lower()}:\n\n{PUBLIC_FIRST_YEAR_URL}"

        return sanitize_text(answer), sources

    # Case 2: Multiple matching documents found
    subj = query_params.get("subject") or docs[0].get("subject", "Course")
    unit = query_params.get("unit")
    unit_str = f" Unit {unit}" if unit is not None else ""

    is_qp = query_params.get("document_type") == "question_paper" or all(d.get("document_type") == "question_paper" for d in docs)
    if is_qp:
        lines = [f"Yes. I found {subj} question papers:"]
        for d in docs[:8]:
            t_disp = d['title'].strip()
            if t_disp.lower() == "2023 may":
                t_disp = "2023 May"
            elif t_disp.lower() == "2023 sept":
                t_disp = "2023 September"
            lines.append(f"- {t_disp}")
        if len(docs) > 8:
            lines.append(f"*(and {len(docs) - 8} more)*")
        lines.append("\nWhich one would you like?")
        lines.append(f"\nYou can access the first-year question papers here:\n{PUBLIC_FIRST_YEAR_URL}")
        return sanitize_text("\n".join(lines)), sources

    lines = [f"I found {len(docs)} {subj}{unit_str} documents:"]
    for d in docs[:8]:
        lines.append(f"- {d['title']}")

    if len(docs) > 8:
        lines.append(f"*(and {len(docs) - 8} more)*")

    lines.append("\nWhich one would you like to access?")
    lines.append(f"\nYou can access first-year resources here:\n{PUBLIC_FIRST_YEAR_URL}")
    return sanitize_text("\n".join(lines)), sources

