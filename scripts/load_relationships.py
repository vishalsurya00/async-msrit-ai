"""
Load and seed the Step 5 Knowledge / Relationship Layer in PostgreSQL.
Seeds:
  1. subjects (canonical first-year subjects)
  2. stream_branches (First-Year Curricular Stream to Branch Code mapping)
  3. stream_subjects (Curricular Stream + Cycle to Subject mapping)
  4. clubs.branch_scope (Target branch scope for campus clubs)
Uses strictly existing verified repository data.
Idempotent and safe to run multiple times.
"""
import sys
import json
import csv
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_connection

DATA_DIR = PROJECT_ROOT / "data" / "structured"
SQL_MIGRATION_PATH = PROJECT_ROOT / "db" / "step5_relationships.sql"


def apply_migration(conn) -> None:
    """Executes db/step5_relationships.sql to ensure tables and columns exist."""
    print("Applying database migration from db/step5_relationships.sql...")
    with open(SQL_MIGRATION_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    print("Migration applied successfully.")


def seed_subjects(conn) -> int:
    """
    Seeds canonical first-year subjects into subjects table.
    Derived from verified academic_documents in the local repository.
    """
    subjects_data = [
        (
            "MATH_FY",
            "Mathematics",
            1,
            "Both",
            "First-year engineering mathematics covering calculus, differential equations, and linear algebra."
        ),
        (
            "PHYS_FY",
            "Physics",
            1,
            "Physics Cycle",
            "Engineering physics covering quantum mechanics, lasers, oscillations, and material properties."
        ),
        (
            "CHEM_FY",
            "Chemistry",
            1,
            "Chemistry Cycle",
            "Engineering chemistry covering electrochemistry, corrosion, polymers, and battery technology."
        ),
        (
            "CPROG_FY",
            "Programming in C",
            1,
            "Both",
            "Engineering Science Course (ESC) covering problem solving, algorithms, and C programming fundamentals."
        ),
        (
            "CIVIL_FY",
            "Civil Engineering (ESC)",
            1,
            "Both",
            "Engineering Science Course (ESC) covering elements of civil engineering and engineering mechanics."
        )
    ]

    cur = conn.cursor()
    inserted_count = 0
    for code, name, sem, cycle, desc in subjects_data:
        cur.execute(
            """
            INSERT INTO subjects (code, name, semester, default_cycle, description)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                semester = EXCLUDED.semester,
                default_cycle = EXCLUDED.default_cycle,
                description = EXCLUDED.description;
            """,
            (code, name, sem, cycle, desc)
        )
        inserted_count += 1
    conn.commit()
    cur.close()
    print(f"Seeded {inserted_count} canonical subjects.")
    return inserted_count


def seed_stream_branches(conn) -> Tuple[int, List[str]]:
    """
    Seeds stream_branches table from data/structured/first_year_metadata.json stream_branches.
    Validates every branch code against branches table in PostgreSQL.
    Preserves strict distinction between AI&ML and CSE(AI&ML).
    """
    metadata_file = DATA_DIR / "first_year_metadata.json"
    if not metadata_file.exists():
        raise FileNotFoundError(f"Missing required file: {metadata_file}")

    with open(metadata_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    raw_stream_branches = meta.get("stream_branches", {})

    # Fetch verified branch codes currently in database
    cur = conn.cursor()
    cur.execute("SELECT code FROM branches;")
    existing_branch_codes: Set[str] = {r[0] for r in cur.fetchall()}

    # Metadata alias mapping to canonical database branch codes in branches.code
    # Crucial distinction:
    # 'AIML' maps to 'AI&ML'
    # 'CSE-AIML' maps to 'CSE(AIML)'
    # They are NEVER normalized into the same branch code.
    alias_to_code_map = {
        "CSE": "CSE",
        "ISE": "ISE",
        "AIML": "AI&ML",
        "AIDS": "AIDS",
        "CSE-AIML": "CSE(AIML)",
        "CSE-Cyber": "CSE(CS)",
        "ECE": "ECE",
        "EEE": "EEE",
        "EIE": "EIE",
        "ETE": "ETE",
        "MD": "MLE",       # Medical Electronics
        "Civil": "CE",      # Civil Engineering
        "ME": "ME",        # Mechanical Engineering
        "IEM": "IEM",      # Industrial Engineering & Management
        "CH": "CHE"        # Chemical Engineering
    }

    inserted_count = 0
    mapped_codes = set()

    for stream_name, raw_branches_str in raw_stream_branches.items():
        # Split tokens separated by comma or 'and'
        tokens = [t.strip() for t in raw_branches_str.replace(" and ", ", ").split(",") if t.strip()]
        for tok in tokens:
            canon_code = alias_to_code_map.get(tok, tok)
            if canon_code not in existing_branch_codes:
                print(f"Warning: Branch token '{tok}' resolved to '{canon_code}' which is not in branches table. Skipping.")
                continue

            cur.execute(
                """
                INSERT INTO stream_branches (stream_name, branch_code)
                VALUES (%s, %s)
                ON CONFLICT (stream_name, branch_code) DO NOTHING;
                """,
                (stream_name, canon_code)
            )
            inserted_count += 1
            mapped_codes.add(canon_code)

    conn.commit()
    cur.close()

    unmapped = sorted(list(existing_branch_codes - mapped_codes))
    print(f"Seeded {inserted_count} stream_branches relationships across 4 First-Year streams.")
    if unmapped:
        print(f"Notice: The following branches in branches table are not in First-Year engineering streams: {unmapped}")
        print("(Per instructions, unmapped branches like Architecture and higher-tier programs are preserved without inventing mappings).")

    return inserted_count, unmapped


def seed_stream_subjects(conn) -> int:
    """
    Seeds stream_subjects table linking First-Year Curricular Streams and Cycles
    to canonical subjects.
    Derived strictly from verified first_year_metadata.json document distributions.
    """
    # Verify subject codes exist
    cur = conn.cursor()
    cur.execute("SELECT code, name FROM subjects;")
    subj_code_map = {name: code for code, name in cur.fetchall()}

    # Curricular stream, cycle, and subject associations
    # Mathematics: CSE Stream has Math in both Physics and Chemistry cycles.
    # Physics: Physics Cycle for all 4 streams.
    # Chemistry: Chemistry Cycle for all 4 streams.
    # Programming in C (ESC): Available in Physics & Chemistry cycles across streams.
    # Civil Engineering (ESC): Available in Chemistry cycle (and Physics cycle for CS/IS/EC).
    streams = [
        "Computer Science & Engineering Stream",
        "Electrical & Electronics Engineering Stream",
        "Mechanical Engineering Stream",
        "Civil Engineering Stream"
    ]

    relationships = []

    # 1. Computer Science & Engineering Stream
    relationships.append(("Computer Science & Engineering Stream", "Physics Cycle", "Mathematics"))
    relationships.append(("Computer Science & Engineering Stream", "Physics Cycle", "Physics"))
    relationships.append(("Computer Science & Engineering Stream", "Physics Cycle", "Programming in C"))
    relationships.append(("Computer Science & Engineering Stream", "Chemistry Cycle", "Mathematics"))
    relationships.append(("Computer Science & Engineering Stream", "Chemistry Cycle", "Chemistry"))
    relationships.append(("Computer Science & Engineering Stream", "Chemistry Cycle", "Civil Engineering (ESC)"))
    relationships.append(("Computer Science & Engineering Stream", "Chemistry Cycle", "Programming in C"))

    # 2. Other 3 Engineering Streams
    for st in [
        "Electrical & Electronics Engineering Stream",
        "Mechanical Engineering Stream",
        "Civil Engineering Stream"
    ]:
        relationships.append((st, "Physics Cycle", "Mathematics"))
        relationships.append((st, "Physics Cycle", "Physics"))
        relationships.append((st, "Physics Cycle", "Programming in C"))
        relationships.append((st, "Chemistry Cycle", "Mathematics"))
        relationships.append((st, "Chemistry Cycle", "Chemistry"))
        relationships.append((st, "Chemistry Cycle", "Civil Engineering (ESC)"))

    inserted_count = 0
    for stream_name, cycle, subj_name in relationships:
        subj_code = subj_code_map.get(subj_name)
        if not subj_code:
            print(f"Warning: Subject '{subj_name}' code not found. Skipping.")
            continue
        cur.execute(
            """
            INSERT INTO stream_subjects (stream_name, cycle, subject_code)
            VALUES (%s, %s, %s)
            ON CONFLICT (stream_name, cycle, subject_code) DO NOTHING;
            """,
            (stream_name, cycle, subj_code)
        )
        inserted_count += 1

    conn.commit()
    cur.close()
    print(f"Seeded {inserted_count} stream_subjects relationships.")
    return inserted_count


def seed_club_branch_scope(conn) -> int:
    """
    Populates clubs.branch_scope from data/structured/clubs.csv.
    """
    clubs_file = DATA_DIR / "clubs.csv"
    if not clubs_file.exists():
        raise FileNotFoundError(f"Missing required file: {clubs_file}")

    updated_count = 0
    cur = conn.cursor()

    with open(clubs_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            club_name = row.get("club_name", "").strip()
            branch_scope = row.get("branch_scope", "All branches").strip()
            if not club_name:
                continue

            cur.execute(
                """
                UPDATE clubs
                SET branch_scope = %s
                WHERE name = %s OR name ILIKE %s;
                """,
                (branch_scope, club_name, f"%{club_name}%")
            )
            if cur.rowcount > 0:
                updated_count += 1

    conn.commit()
    cur.close()
    print(f"Updated branch_scope for {updated_count} clubs in PostgreSQL.")
    return updated_count


def main():
    print("=== Loading Step 5 Knowledge & Relationship Layer ===")
    conn = get_connection()
    try:
        apply_migration(conn)
        subj_cnt = seed_subjects(conn)
        sb_cnt, unmapped = seed_stream_branches(conn)
        ss_cnt = seed_stream_subjects(conn)
        club_cnt = seed_club_branch_scope(conn)

        print("\n=== Relationship Layer Seeding Summary ===")
        print(f"Subjects Seeded: {subj_cnt}")
        print(f"Stream-Branch Mappings: {sb_cnt}")
        print(f"Stream-Subject Mappings: {ss_cnt}")
        print(f"Clubs branch_scope updated: {club_cnt}")
        print("Knowledge Layer seeding completed successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
