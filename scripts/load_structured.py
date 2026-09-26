"""
Load structured campus data (branches and clubs) into PostgreSQL.
Supports both CSV and Excel (.xlsx) formats from data/structured/.
"""
import os
import sys
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_connection


def read_tabular_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Read tabular data from CSV or Excel (.xlsx/.xls) into a list of dictionaries.
    """
    if not file_path.exists():
        return []

    suffix = file_path.suffix.lower()
    records = []

    if suffix == ".csv":
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys (stripped) and values (stripped)
                cleaned_row = {
                    (k.strip() if k else ""): (v.strip() if isinstance(v, str) else v)
                    for k, v in row.items()
                    if k is not None
                }
                records.append(cleaned_row)

    elif suffix in [".xlsx", ".xls"]:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active
            rows = list(sheet.iter_rows(values_only=True))
            if rows:
                headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
                for row in rows[1:]:
                    if any(val is not None and str(val).strip() != "" for val in row):
                        record = {
                            headers[i]: (str(val).strip() if val is not None else "")
                            for i, val in enumerate(row)
                            if i < len(headers)
                        }
                        records.append(record)
        except ImportError:
            print(f"Warning: openpyxl is not installed, cannot read {file_path.name}", file=sys.stderr)
        except Exception as e:
            print(f"Error reading {file_path.name} with openpyxl: {e}", file=sys.stderr)

    return records


def find_file(structured_dir: Path, candidate_names: List[str]) -> Optional[Path]:
    """Find the first matching file among candidate filenames in directory."""
    for name in candidate_names:
        p = structured_dir / name
        if p.exists():
            return p
    return None


def get_field(row: Dict[str, Any], candidate_keys: List[str], default: str = "") -> str:
    """Retrieve the first matching key from a dictionary, case-insensitive."""
    for cand in candidate_keys:
        # Direct check
        if cand in row and row[cand]:
            return str(row[cand]).strip()
        # Case-insensitive check
        cand_lower = cand.lower()
        for k, v in row.items():
            if k and k.lower() == cand_lower and v:
                return str(v).strip()
    return default


def load_branches(conn, structured_dir: Path) -> int:
    """
    Load branches into PostgreSQL.
    Upserts using ON CONFLICT (code) DO UPDATE.
    """
    branch_candidates = ["branches.csv", "branches.xlsx", "branches.xls"]
    branch_file = find_file(structured_dir, branch_candidates)
    if not branch_file:
        print(f"No branch file found in {structured_dir} (checked {branch_candidates})")
        return 0

    print(f"Loading branches from: {branch_file.name}")
    rows = read_tabular_file(branch_file)
    if not rows:
        print("No rows found in branch file.")
        return 0

    upsert_sql = """
        INSERT INTO branches (code, name, stream, hod_name, location)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            stream = EXCLUDED.stream,
            hod_name = EXCLUDED.hod_name,
            location = EXCLUDED.location;
    """

    loaded_count = 0
    with conn.cursor() as cur:
        for row in rows:
            code = get_field(row, ["Branch Code", "code", "branch_code"])
            name = get_field(row, ["Branch Full Name", "name", "branch_name"])
            stream = get_field(row, ["Stream", "stream"])
            hod_name = get_field(row, ["Name of HOD", "hod_name", "hod"])
            location = get_field(row, ["Dept Office Location", "location", "dept_office_location"])

            if not code or not name:
                continue

            cur.execute(upsert_sql, (code, name, stream, hod_name, location))
            loaded_count += 1

    conn.commit()
    return loaded_count


def load_clubs(conn, structured_dir: Path) -> int:
    """
    Load clubs into PostgreSQL.
    Truncates table and inserts fresh records.
    """
    club_candidates = ["clubs.csv", "clubs.xlsx", "clubs_2.xlsx", "clubs.xls"]
    club_file = find_file(structured_dir, club_candidates)
    if not club_file:
        print(f"No club file found in {structured_dir} (checked {club_candidates})")
        return 0

    print(f"Loading clubs from: {club_file.name}")
    rows = read_tabular_file(club_file)
    if not rows:
        print("No rows found in club file.")
        return 0

    insert_sql = """
        INSERT INTO clubs (name, category, lead_name, description)
        VALUES (%s, %s, %s, %s);
    """

    loaded_count = 0
    with conn.cursor() as cur:
        # Truncate and reset identity for clean loading
        cur.execute("TRUNCATE TABLE clubs RESTART IDENTITY;")

        for row in rows:
            name = get_field(row, ["club_name", "name", "Club Name"])
            category = get_field(row, ["category", "Category"])
            lead_name = get_field(row, ["branch_scope", "lead_name", "Lead Name", "Branch Scope"])
            description = get_field(row, ["description", "Description"])

            if not name:
                continue

            cur.execute(insert_sql, (name, category, lead_name, description))
            loaded_count += 1

    conn.commit()
    return loaded_count



def load_academic_documents(conn, structured_dir: Path) -> int:
    """
    Load verified academic documents metadata into PostgreSQL.
    Extracts documents from first_year_metadata.json and links with first_year_links.json.
    """
    meta_path = structured_dir / "first_year_metadata.json"
    if not meta_path.exists():
        print(f"No academic documents metadata found at {meta_path}")
        return 0

    links_path = structured_dir / "first_year_links.json"
    folder_to_url = {}
    if links_path.exists():
        try:
            links_data = json.loads(links_path.read_text(encoding="utf-8"))
            for r in links_data.get("records", []):
                if r.get("folder_id") and r.get("folder_url"):
                    folder_to_url[r["folder_id"]] = r["folder_url"]
        except Exception as e:
            print(f"Warning reading {links_path}: {e}", file=sys.stderr)

    try:
        docs_data = json.loads(meta_path.read_text(encoding="utf-8"))
        docs = docs_data.get("documents", [])
    except Exception as e:
        print(f"Error reading {meta_path}: {e}", file=sys.stderr)
        return 0

    type_mapping = {
        "notes": "notes",
        "quick_revision": "study_material",
        "practice_problems": "study_material",
        "lab_manual": "lab_manual",
        "syllabus": "syllabus",
        "question_paper": "question_paper",
        "cie_paper": "question_paper",
        "textbook": "study_material"
    }

    insert_sql = """
        INSERT INTO academic_documents (
            document_id, title, subject, semester, branch, stream, cycle, unit,
            document_type, year, source_url, local_file_path
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (document_id) DO UPDATE SET
            title = EXCLUDED.title,
            subject = EXCLUDED.subject,
            semester = EXCLUDED.semester,
            branch = EXCLUDED.branch,
            stream = EXCLUDED.stream,
            cycle = EXCLUDED.cycle,
            unit = EXCLUDED.unit,
            document_type = EXCLUDED.document_type,
            year = EXCLUDED.year,
            source_url = EXCLUDED.source_url,
            local_file_path = EXCLUDED.local_file_path;
    """

    loaded = 0
    with conn.cursor() as cur:
        for doc in docs:
            p = doc.get("path", "")
            fn = doc.get("file_name", "")
            raw_type = doc.get("doc_type", "notes")
            canon_type = type_mapping.get(raw_type, "notes")
            unit = doc.get("unit")
            exam_yr = str(doc.get("exam_year")) if doc.get("exam_year") else None

            src_url = ""
            source_urls = doc.get("source_folder_urls", [])
            if source_urls:
                src_url = source_urls[0]
            else:
                for fid, furl in folder_to_url.items():
                    if fid in p:
                        src_url = furl
                        break

            subjects_info = doc.get("subjects", [])
            subjs = list({s.get("subject") for s in subjects_info if s.get("subject")})
            subject = subjs[0] if subjs else "General"
            if "esc" in p.lower() and "c programming" in p.lower():
                subject = "Programming in C"
            elif "esc" in p.lower() and "civil" in p.lower():
                subject = "Civil Engineering (ESC)"
            elif "esc" in p.lower() and "mechanical" in p.lower():
                subject = "Mechanical Engineering (ESC)"

            streams = doc.get("streams", [])
            cycles = doc.get("cycles", [])

            cur.execute(insert_sql, (
                doc.get("doc_id"),
                fn.replace(".pdf", "").strip(),
                subject,
                1,
                None,
                ", ".join(streams) if isinstance(streams, list) else str(streams),
                ", ".join(cycles) if isinstance(cycles, list) else str(cycles),
                unit,
                canon_type,
                exam_yr,
                src_url,
                p
            ))
            loaded += 1

    conn.commit()
    return loaded


def main():
    structured_dir = PROJECT_ROOT / "data" / "structured"
    if not structured_dir.exists():
        print(f"Error: Structured directory not found at {structured_dir}", file=sys.stderr)
        sys.exit(1)

    print("Connecting to PostgreSQL...")
    conn = get_connection()
    try:
        branches_count = load_branches(conn, structured_dir)
        clubs_count = load_clubs(conn, structured_dir)
        docs_count = load_academic_documents(conn, structured_dir)

        print("\n--- Structured Data Loading Summary ---")
        print(f"Successfully loaded {branches_count} branches.")
        print(f"Successfully loaded {clubs_count} clubs.")
        print(f"Successfully loaded {docs_count} academic documents.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

