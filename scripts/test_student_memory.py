"""
Step 3 Test Suite: Persistent Student Memory + Personalization
Tests intent classification, natural language extraction, PostgreSQL persistence,
partial profile updates, canonical branch representation, profile queries,
and runs Step 1 & Step 2 regression suites.
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import classify_intent, handle_message, _extract_profile_data
from backend.memory import (
    get_student_profile,
    update_student_profile,
    delete_student_profile,
    validate_and_normalize_profile_fields,
    normalize_canonical_branch
)
from backend.mcp_client import mcp_session
from db.connection import get_connection


async def test_intents():
    print("\n--- 1. Testing Profile Intent Classification ---")
    intent_cases = [
        # Explicit profile update commands
        ("update semester with 3", "memory_update"),
        ("update my semester with 3", "memory_update"),
        ("update semester to 3", "memory_update"),
        ("change my semester to 3", "memory_update"),
        ("set semester to 3", "memory_update"),
        ("update my branch with ECE", "memory_update"),
        ("update branch to ECE", "memory_update"),
        ("change my branch to ECE", "memory_update"),
        ("set my branch as ECE", "memory_update"),

        # Natural profile statements
        ("My name is Vishal", "memory_update"),
        ("My branch is AI&ML", "memory_update"),
        ("My semester is 3", "memory_update"),
        ("My CGPA is 8.97", "memory_update"),
        ("I am in semester 3", "memory_update"),
        ("I scored 8.5 CGPA", "memory_update"),
        ("I am studying in CSE(AI&ML), semester 3", "memory_update"),
        ("Update my profile with Semester: 3", "memory_update"),
        ("Update my profile", "memory_update"),
        ("My CGPA is abc", "memory_update"),

        # Student Identity Query Variants (Requirement 2)
        ("Who am I?", "memory_query"),
        ("who am i", "memory_query"),
        ("who i am", "memory_query"),
        ("tell me who i am", "memory_query"),
        ("tell me about myself", "memory_query"),
        ("what do you know about me", "memory_query"),

        # Profile Field Query Variants (Requirement 3)
        ("What branch am I in?", "memory_query"),
        ("Which is my branch?", "memory_query"),
        ("Which branch am I in?", "memory_query"),
        ("What is my branch?", "memory_query"),
        ("Tell me my branch", "memory_query"),
        ("What is my semester?", "memory_query"),
        ("Which semester am I in?", "memory_query"),
        ("Tell me my semester", "memory_query"),
        ("What is my CGPA?", "memory_query"),
        ("Tell me my CGPA", "memory_query"),
        ("What CGPA do I have?", "memory_query"),
        ("What is my name?", "memory_query"),
        ("Tell me my name", "memory_query"),

        # Department Regression (Requirement 5)
        ("Who is the HOD of CSE?", "department"),
        ("Where is CSE?", "department"),
        ("Tell me about CSE", "department"),
        ("Who is the HOD of ECE?", "department"),

        # Identity & academic RAG intents
        ("Who are you?", "identity"),
        ("Who r u?", "identity"),
        ("Explain Laplace Transform", "academic"),
        ("Explain recursion", "academic"),
        ("Give me Maths Unit 1 PDF", "document_retrieval"),
        ("AI&ML", "department"),
        ("CSE(AI&ML)", "department")
    ]

    for q, expected in intent_cases:
        res = classify_intent(q)
        assert res["type"] == expected, f"Intent mismatch for '{q}': expected {expected}, got {res['type']}"
        print(f"  [OK] Intent: '{q}' -> {res['type']}")
    print("  -> Intent tests: PASSED")


def test_extraction():
    print("\n--- 2. Testing Natural-Language Profile Extraction ---")

    # Semester update commands with prepositions
    sem_cases = [
        ("update semester with 3", 3),
        ("update my semester with 3", 3),
        ("update semester to 3", 3),
        ("change my semester to 3", 3),
        ("set semester to 3", 3),
        ("I am in semester 3", 3),
        ("My current semester is 3", 3),
    ]
    for q, expected in sem_cases:
        d, inv = _extract_profile_data(q)
        assert d.get("semester") == expected, f"Failed semester extraction for '{q}': got {d}, inv={inv}"
        print(f"  [OK] Semester extraction: '{q}' -> {d.get('semester')}")

    # Branch update commands with prepositions
    br_cases = [
        ("update my branch with ECE", "ECE"),
        ("update branch to ECE", "ECE"),
        ("change my branch to ECE", "ECE"),
        ("set my branch as ECE", "ECE"),
    ]
    for q, expected in br_cases:
        d, inv = _extract_profile_data(q)
        assert d.get("branch") == expected, f"Failed branch extraction for '{q}': got {d}, inv={inv}"
        print(f"  [OK] Branch extraction: '{q}' -> {d.get('branch')}")

    # Canonical branch representation (Requirement 4)
    d_aiml, _ = _extract_profile_data("My branch is AI&ML")
    assert d_aiml.get("branch") == "AI&ML", f"Expected 'AI&ML', got {d_aiml}"

    d_cse_aiml, _ = _extract_profile_data("I am studying in CSE(AI&ML)")
    assert d_cse_aiml.get("branch") == "CSE(AI&ML)", f"Expected 'CSE(AI&ML)', got {d_cse_aiml}"
    assert d_aiml.get("branch") != d_cse_aiml.get("branch"), "AI&ML and CSE(AI&ML) must remain distinct database values!"
    print(f"  [OK] Branch canonical: AI&ML -> {d_aiml.get('branch')}, CSE(AI&ML) -> {d_cse_aiml.get('branch')}")

    # Name extraction
    d_n1, _ = _extract_profile_data("My name is Vishal")
    assert d_n1.get("name") == "Vishal", f"Failed name extraction: {d_n1}"

    d_n2, _ = _extract_profile_data("I am Vishal")
    assert d_n2.get("name") == "Vishal", f"Failed 'I am Vishal': {d_n2}"

    d_n3, _ = _extract_profile_data("You can call me Vinayak")
    assert d_n3.get("name") == "Vinayak", f"Failed 'call me Vinayak': {d_n3}"

    d_n4, _ = _extract_profile_data("My name is Vishal Kumar")
    assert d_n4.get("name") == "Vishal Kumar", f"Failed 'Vishal Kumar': {d_n4}"

    # CGPA extraction
    d_g1, _ = _extract_profile_data("My CGPA is 8.97")
    assert d_g1.get("cgpa") == 8.97, f"Failed CGPA 8.97: {d_g1}"

    d_g2, _ = _extract_profile_data("I scored 8.5 CGPA")
    assert d_g2.get("cgpa") == 8.5, f"Failed scored 8.5 CGPA: {d_g2}"

    d_g3, _ = _extract_profile_data("update CGPA to 9.1")
    assert d_g3.get("cgpa") == 9.1, f"Failed update CGPA 9.1: {d_g3}"

    # College and Degree extraction
    dc1, _ = _extract_profile_data("I study at MSRIT")
    assert dc1.get("college") == "MSRIT", f"Failed college MSRIT: {dc1}"

    dd1, _ = _extract_profile_data("I am pursuing BE")
    assert dd1.get("degree") == "BE", f"Failed degree BE: {dd1}"

    # Multi-field extraction
    dm1, _ = _extract_profile_data("My name is Vishal and I am studying BE in CSE(AI&ML), semester 3")
    assert dm1.get("name") == "Vishal", f"Multi-field name failed: {dm1}"
    assert dm1.get("degree") == "BE", f"Multi-field degree failed: {dm1}"
    assert dm1.get("branch") == "CSE(AI&ML)", f"Multi-field branch failed: {dm1}"
    assert dm1.get("semester") == 3, f"Multi-field semester failed: {dm1}"

    # Invalid value handling
    _, inv1 = _extract_profile_data("My CGPA is abc")
    assert "cgpa" in inv1, f"Expected invalid cgpa: {inv1}"

    _, inv2 = _extract_profile_data("I am in semester 42")
    assert "semester" in inv2, f"Expected invalid semester: {inv2}"

    print("  -> Extraction tests: PASSED")


def test_canonical_branch_normalization():
    print("\n--- 3. Testing Canonical Branch Normalization Rules ---")
    # AI&ML and CSE(AI&ML) are different branches
    assert normalize_canonical_branch("AI&ML") == "AI&ML"
    assert normalize_canonical_branch("aiml") == "AI&ML"
    assert normalize_canonical_branch("ai & ml") == "AI&ML"
    assert normalize_canonical_branch("ai and ml") == "AI&ML"

    assert normalize_canonical_branch("CSE(AI&ML)") == "CSE(AI&ML)"
    assert normalize_canonical_branch("CSE(AIML)") == "CSE(AI&ML)"
    assert normalize_canonical_branch("cse aiml") == "CSE(AI&ML)"
    assert normalize_canonical_branch("cse (ai&ml)") == "CSE(AI&ML)"
    assert normalize_canonical_branch("cse-aiml") == "CSE(AI&ML)"

    # Never normalize CSE(AI&ML) -> AI&ML
    assert normalize_canonical_branch("CSE(AI&ML)") != "AI&ML"
    assert normalize_canonical_branch("CSE(AIML)") != "AI&ML"

    # Other canonical branches
    assert normalize_canonical_branch("cse") == "CSE"
    assert normalize_canonical_branch("ece") == "ECE"
    assert normalize_canonical_branch("mech") == "ME"
    assert normalize_canonical_branch("civil") == "CE"

    print("  -> Canonical branch normalization tests: PASSED")


async def test_persistence_and_safe_partial_updates():
    print("\n--- 4. Testing Persistence and Safe Partial Updates (Requirements 6 & 7) ---")
    test_sid = "test_student_memory_step3_suite"

    # Start with a clean slate
    delete_student_profile(test_sid)

    async with mcp_session():
        # Setup initial profile: Name: Vishal, Branch: AI&ML, Semester: 3, CGPA: 8.97
        print("  -> Setting initial profile fields...")
        u1 = await handle_message("My name is Vishal", test_sid)
        assert u1.get("action_taken") == "update_student_profile"
        assert "Vishal" in u1.get("answer")

        u2 = await handle_message("My branch is AI&ML", test_sid)
        assert u2.get("action_taken") == "update_student_profile"
        assert "AI&ML" in u2.get("answer")

        u3 = await handle_message("My semester is 3", test_sid)
        assert u3.get("action_taken") == "update_student_profile"
        assert "3" in u3.get("answer")

        u4 = await handle_message("My CGPA is 8.97", test_sid)
        assert u4.get("action_taken") == "update_student_profile"
        assert "8.97" in u4.get("answer")

        # Verify initial profile stored correctly
        prof_init = get_student_profile(test_sid)
        assert prof_init is not None
        assert prof_init["name"] == "Vishal"
        assert prof_init["branch"] == "AI&ML"
        assert prof_init["semester"] == 3
        assert prof_init["cgpa"] == 8.97
        print(f"  [OK] Initial profile: Name={prof_init['name']}, Branch={prof_init['branch']}, Semester={prof_init['semester']}, CGPA={prof_init['cgpa']}")

        # Test "Who am I?" returns complete stored profile (Requirement 6)
        q_who = await handle_message("Who am I?", test_sid)
        assert q_who.get("action_taken") == "get_student_profile"
        ans_who = q_who.get("answer")
        assert "Vishal" in ans_who
        assert "AI&ML" in ans_who
        assert "3" in ans_who
        assert "8.97" in ans_who
        print("  [OK] 'Who am I?' returned verified stored profile")

        # Test "Which is my branch?" returns branch (Requirement 6)
        q_br = await handle_message("Which is my branch?", test_sid)
        assert q_br.get("action_taken") == "get_student_profile"
        assert "AI&ML" in q_br.get("answer")
        assert "8.97" not in q_br.get("answer"), "Branch query must return only branch"
        print("  [OK] 'Which is my branch?' returned branch")

        # Test "What is my CGPA?" returns only CGPA (Requirement 6)
        q_cg = await handle_message("What is my CGPA?", test_sid)
        assert q_cg.get("action_taken") == "get_student_profile"
        assert "8.97" in q_cg.get("answer")
        assert "Vishal" not in q_cg.get("answer"), "CGPA query must return only CGPA"
        print("  [OK] 'What is my CGPA?' returned only CGPA")

        # Partial update test (Requirement 7):
        # User says: "update semester with 4"
        print("  -> Testing partial update: 'update semester with 4'...")
        u_part = await handle_message("update semester with 4", test_sid)
        assert u_part.get("action_taken") == "update_student_profile"
        assert "4" in u_part.get("answer")

        # Result must be: Name: Vishal, Branch: AI&ML, Semester: 4, CGPA: 8.97
        prof_after = get_student_profile(test_sid)
        assert prof_after["name"] == "Vishal", f"Name must NOT be cleared! Got: {prof_after['name']}"
        assert prof_after["branch"] == "AI&ML", f"Branch must NOT be cleared! Got: {prof_after['branch']}"
        assert prof_after["semester"] == 4, f"Semester must be 4! Got: {prof_after['semester']}"
        assert prof_after["cgpa"] == 8.97, f"CGPA must NOT be cleared! Got: {prof_after['cgpa']}"
        print(f"  [OK] After 'update semester with 4': Name={prof_after['name']}, Branch={prof_after['branch']}, Semester={prof_after['semester']}, CGPA={prof_after['cgpa']}")

        # Also test branch update with ECE does not route to department or clear fields (Requirement 1 & 5)
        u_ece = await handle_message("update my branch with ECE", test_sid)
        assert u_ece.get("action_taken") == "update_student_profile", f"Must NOT route to department lookup! Got: {u_ece.get('action_taken')}"
        assert "ECE" in u_ece.get("answer")

        prof_ece = get_student_profile(test_sid)
        assert prof_ece["branch"] == "ECE"
        assert prof_ece["name"] == "Vishal"
        assert prof_ece["semester"] == 4
        assert prof_ece["cgpa"] == 8.97
        print("  [OK] 'update my branch with ECE' safely updated branch to ECE without clearing other fields")

        # Direct DB connection persistence verification
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, branch, semester, cgpa FROM student_profile WHERE student_id = %s;", (test_sid,))
        db_row = cur.fetchone()
        cur.close()
        conn.close()

        assert db_row is not None
        assert db_row[0] == "Vishal"
        assert db_row[1] == "ECE"
        assert db_row[2] == 4
        assert float(db_row[3]) == 8.97
        print("  [OK] Persistence across independent database connections verified")

        # Clean up test user
        delete_student_profile(test_sid)

    print("  -> Persistence & partial update tests: PASSED")


async def test_identity_and_field_query_variants():
    print("\n--- 5. Testing Student Identity & Field Query Variants (Requirements 2 & 3) ---")
    test_sid = "test_student_query_variants"
    delete_student_profile(test_sid)

    async with mcp_session():
        # Populate student profile
        await handle_message("My name is Vishal", test_sid)
        await handle_message("My branch is AI&ML", test_sid)
        await handle_message("My semester is 3", test_sid)
        await handle_message("My CGPA is 8.97", test_sid)

        # 1. Identity query variants (Requirement 2)
        id_queries = [
            "Who am I?",
            "who am i",
            "who i am",
            "tell me who i am",
            "tell me about myself",
            "what do you know about me"
        ]
        for q in id_queries:
            res = await handle_message(q, test_sid)
            assert res.get("action_taken") == "get_student_profile", f"Failed for '{q}': {res.get('action_taken')}"
            ans = res.get("answer")
            assert "Vishal" in ans, f"Failed for '{q}': {ans}"
            assert "AI&ML" in ans, f"Failed for '{q}': {ans}"
            print(f"  [OK] Identity query: '{q}' -> recognized & profile returned")

        # 2. Branch query variants (Requirement 3)
        br_queries = [
            "What branch am I in?",
            "Which is my branch?",
            "Which branch am I in?",
            "What is my branch?",
            "Tell me my branch"
        ]
        for q in br_queries:
            res = await handle_message(q, test_sid)
            assert res.get("action_taken") == "get_student_profile", f"Failed for '{q}'"
            ans = res.get("answer")
            assert "AI&ML" in ans, f"Branch not found in '{q}': {ans}"
            assert "8.97" not in ans, f"Single-field query '{q}' leaked CGPA: {ans}"
            assert "Vishal" not in ans, f"Single-field query '{q}' leaked Name: {ans}"
            print(f"  [OK] Branch query: '{q}' -> only branch returned")

        # 3. Semester query variants (Requirement 3)
        sem_queries = [
            "What is my semester?",
            "Which semester am I in?",
            "Tell me my semester"
        ]
        for q in sem_queries:
            res = await handle_message(q, test_sid)
            assert res.get("action_taken") == "get_student_profile", f"Failed for '{q}'"
            ans = res.get("answer")
            assert "3" in ans, f"Semester not found in '{q}': {ans}"
            assert "8.97" not in ans, f"Single-field query '{q}' leaked CGPA: {ans}"
            print(f"  [OK] Semester query: '{q}' -> only semester returned")

        # 4. CGPA query variants (Requirement 3)
        cgpa_queries = [
            "What is my CGPA?",
            "Tell me my CGPA",
            "What CGPA do I have?"
        ]
        for q in cgpa_queries:
            res = await handle_message(q, test_sid)
            assert res.get("action_taken") == "get_student_profile", f"Failed for '{q}'"
            ans = res.get("answer")
            assert "8.97" in ans, f"CGPA not found in '{q}': {ans}"
            assert "AI&ML" not in ans, f"Single-field query '{q}' leaked branch: {ans}"
            print(f"  [OK] CGPA query: '{q}' -> only CGPA returned")

        # 5. Name query variants (Requirement 3)
        name_queries = [
            "What is my name?",
            "Tell me my name"
        ]
        for q in name_queries:
            res = await handle_message(q, test_sid)
            assert res.get("action_taken") == "get_student_profile", f"Failed for '{q}'"
            ans = res.get("answer")
            assert "Vishal" in ans, f"Name not found in '{q}': {ans}"
            assert "8.97" not in ans, f"Single-field query '{q}' leaked CGPA: {ans}"
            print(f"  [OK] Name query: '{q}' -> only name returned")

        delete_student_profile(test_sid)

    print("  -> Identity and field query variant tests: PASSED")


async def main():
    print("=" * 70)
    print("RIT NEXUS — STEP 3 BUG-FIX REGRESSION TEST SUITE")
    print("=" * 70)

    # 1. Intent classification
    await test_intents()

    # 2. Extraction
    test_extraction()

    # 3. Canonical branch normalization
    test_canonical_branch_normalization()

    # 4. Persistence and safe partial updates
    await test_persistence_and_safe_partial_updates()

    # 5. Identity and field query variants
    await test_identity_and_field_query_variants()

    # 6. Step 1 regression suite
    print("\n--- 6. Running Step 1 Regression Suite ---")
    from scripts.test_department_responses import run_tests as run_step1_tests
    await run_step1_tests()

    # 7. Step 2 regression suite
    print("\n--- 7. Running Step 2 Regression Suite ---")
    from scripts.test_academic_documents import main as run_step2_tests
    await run_step2_tests()

    print("\n" + "=" * 70)
    print("ALL STEP 3 REGRESSION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
