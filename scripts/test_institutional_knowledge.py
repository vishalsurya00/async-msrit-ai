"""
Comprehensive regression test suite for RIT NEXUS Institutional Knowledge,
Entity Counts, Formatting Strictness, Multi-Turn Pronoun & Entity Follow-ups,
and Stale-Context Guards across all 15 tests specified in the prompt.
"""
import sys
import os
import asyncio
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import handle_message, classify_intent
from backend.conversation_store import create_session, delete_session
from backend.info_lookup import (
    get_branch_count,
    get_club_count,
    list_branches_names,
    list_clubs_names,
    get_principal_info,
    get_chief_proctor_info,
    get_apex_ground_floor_offices
)


async def run_tests():
    print("=" * 80)
    print("STARTING INSTITUTIONAL KNOWLEDGE & 15 PROMPT REGRESSION TESTS")
    print("=" * 80)

    total_tests = 0
    passed_tests = 0

    def assert_test(cond: bool, desc: str, detail: str = ""):
        nonlocal total_tests, passed_tests
        total_tests += 1
        if cond:
            passed_tests += 1
            print(f"[PASS] TEST {total_tests}: {desc}")
        else:
            print(f"[FAIL] TEST {total_tests}: {desc} -> {detail}")
            raise AssertionError(f"Test failed: {desc} -> {detail}")

    # -------------------------------------------------------------------------
    # TEST 1: Department HOD -> Follow-up "Where is that department?"
    # ECE HOD -> "Where is that department?" -> ECE + DES Block + 2nd Floor
    # -------------------------------------------------------------------------
    sess1 = create_session(student_id="test_user")
    try:
        r1_1 = await handle_message("Who is the HOD of ECE?", student_id="test_user", session_id=sess1)
        ans1_1 = r1_1.get("answer", "")
        assert "Raghuram" in ans1_1 or "ECE" in ans1_1, f"Turn 1 expected ECE HOD: {ans1_1}"

        r1_2 = await handle_message("Where is that department?", student_id="test_user", session_id=sess1)
        ans1_2 = r1_2.get("answer", "")
        print(f"Test 1 Ans: {ans1_2}")
        cond1 = ("ECE" in ans1_2 or "Electronics" in ans1_2) and "DES Block" in ans1_2 and "2nd floor" in ans1_2.lower()
        assert_test(cond1, "ECE HOD -> 'Where is that department?' resolves to ECE in DES Block, 2nd Floor", ans1_2)
    finally:
        delete_session(sess1)

    # -------------------------------------------------------------------------
    # TEST 2: Where is CSE(AIML)? -> Who is its HOD?
    # CSE(AIML) + Dr. Siddesh G. M.
    # -------------------------------------------------------------------------
    sess2 = create_session(student_id="test_user")
    try:
        r2_1 = await handle_message("Where is the CSE(AIML) department?", student_id="test_user", session_id=sess2)
        ans2_1 = r2_1.get("answer", "")
        assert "Multipurpose Block" in ans2_1 or "5th floor" in ans2_1.lower(), f"Turn 1 expected Multipurpose Block: {ans2_1}"

        r2_2 = await handle_message("Who is its HOD?", student_id="test_user", session_id=sess2)
        ans2_2 = r2_2.get("answer", "")
        print(f"Test 2 Ans: {ans2_2}")
        cond2 = "Siddesh" in ans2_2 and "CSE(AIML)" in ans2_2
        assert_test(cond2, "Where is CSE(AIML)? -> 'Who is its HOD?' resolves to Dr. Siddesh G. M.", ans2_2)
    finally:
        delete_session(sess2)

    # -------------------------------------------------------------------------
    # TEST 3: Who is the principal? -> Where is his office?
    # Dr. B. Sathish Babu then Ground Floor + Apex Block.
    # -------------------------------------------------------------------------
    sess3 = create_session(student_id="test_user")
    try:
        r3_1 = await handle_message("Who is the principal?", student_id="test_user", session_id=sess3)
        ans3_1 = r3_1.get("answer", "")
        assert "Sathish Babu" in ans3_1, f"Expected Dr. B. Sathish Babu: {ans3_1}"

        r3_2 = await handle_message("Where is his office?", student_id="test_user", session_id=sess3)
        ans3_2 = r3_2.get("answer", "")
        print(f"Test 3 Ans: {ans3_2}")
        cond3 = "Ground Floor" in ans3_2 and "Apex Block" in ans3_2
        assert_test(cond3, "Who is principal? -> 'Where is his office?' resolves to Ground Floor, Apex Block", ans3_2)
    finally:
        delete_session(sess3)

    # -------------------------------------------------------------------------
    # TEST 4: Who is the chief proctor? -> Where is her office?
    # Dr. Monica R. Mundada then 1st Floor + Apex Block.
    # -------------------------------------------------------------------------
    sess4 = create_session(student_id="test_user")
    try:
        r4_1 = await handle_message("Who is the chief proctor?", student_id="test_user", session_id=sess4)
        ans4_1 = r4_1.get("answer", "")
        assert "Monica" in ans4_1 and "Mundada" in ans4_1, f"Expected Dr. Monica R. Mundada: {ans4_1}"

        r4_2 = await handle_message("Where is her office?", student_id="test_user", session_id=sess4)
        ans4_2 = r4_2.get("answer", "")
        print(f"Test 4 Ans: {ans4_2}")
        cond4 = "1st Floor" in ans4_2 and "Apex Block" in ans4_2
        assert_test(cond4, "Who is chief proctor? -> 'Where is her office?' resolves to 1st Floor, Apex Block", ans4_2)
    finally:
        delete_session(sess4)

    # -------------------------------------------------------------------------
    # TEST 5: How many branches are there? (Count ONLY)
    # Expected format: "18 branches." (no descriptions)
    # -------------------------------------------------------------------------
    db_branch_count = get_branch_count()
    r5 = await handle_message("How many branches are there in MSRIT?", student_id="test_user")
    ans5 = r5.get("answer", "").strip()
    print(f"Test 5 Ans: {ans5}")
    cond5 = ans5 == f"{db_branch_count} branches."
    assert_test(cond5, f"Count only branches returns strictly '{db_branch_count} branches.'", ans5)

    # -------------------------------------------------------------------------
    # TEST 6: How many clubs are there? (Count ONLY)
    # Expected format: "24 clubs." (no descriptions)
    # -------------------------------------------------------------------------
    db_club_count = get_club_count()
    r6 = await handle_message("How many clubs are there?", student_id="test_user")
    ans6 = r6.get("answer", "").strip()
    print(f"Test 6 Ans: {ans6}")
    cond6 = ans6 == f"{db_club_count} clubs."
    assert_test(cond6, f"Count only clubs returns strictly '{db_club_count} clubs.'", ans6)

    # -------------------------------------------------------------------------
    # TEST 7: How many branches are there and what are their names? (COUNT + NAMES ONLY)
    # -------------------------------------------------------------------------
    r7 = await handle_message("How many branches are there and what are their names?", student_id="test_user")
    ans7 = r7.get("answer", "")
    print(f"Test 7 Ans (preview): {ans7[:120]}...")
    cond7 = (
        f"There are {db_branch_count} branches:" in ans7
        and "Computer Science & Engineering" in ans7
        and "Mechanical Engineering" in ans7
        and "HOD:" not in ans7
        and "Office Location:" not in ans7
    )
    assert_test(cond7, "Count + names for branches returns only count and numbered names", ans7[:200])

    # -------------------------------------------------------------------------
    # TEST 8: How many clubs are there and what are their names? (COUNT + NAMES ONLY)
    # -------------------------------------------------------------------------
    r8 = await handle_message("How many clubs are there and what are their names?", student_id="test_user")
    ans8 = r8.get("answer", "")
    print(f"Test 8 Ans (preview): {ans8[:120]}...")
    cond8 = (
        f"There are {db_club_count} clubs:" in ans8
        and "CodeRIT" in ans8
        and "Lead:" not in ans8
        and "Description:" not in ans8
    )
    assert_test(cond8, "Count + names for clubs returns only count and numbered names", ans8[:200])

    # -------------------------------------------------------------------------
    # TEST 9: List all branches. (NAMES ONLY)
    # -------------------------------------------------------------------------
    r9 = await handle_message("List all branches.", student_id="test_user")
    ans9 = r9.get("answer", "")
    cond9 = (
        "Branches at MSRIT:" in ans9
        and "1." in ans9
        and "Computer Science" in ans9
        and "HOD:" not in ans9
        and "Location:" not in ans9
    )
    assert_test(cond9, "List all branches returns only names without descriptions or HODs", ans9[:200])

    # -------------------------------------------------------------------------
    # TEST 10: List all clubs. (NAMES ONLY)
    # -------------------------------------------------------------------------
    r10 = await handle_message("List all clubs.", student_id="test_user")
    ans10 = r10.get("answer", "")
    cond10 = (
        "Clubs at MSRIT:" in ans10
        and "1." in ans10
        and "CodeRIT" in ans10
        and "Lead / Scope:" not in ans10
        and "Description:" not in ans10
    )
    assert_test(cond10, "List all clubs returns only names without descriptions", ans10[:200])

    # -------------------------------------------------------------------------
    # TEST 11: ECE HOD -> "Give me Physics Unit 1 notes" (No stale context bleed)
    # Second query MUST remain academic document query, no ECE context.
    # -------------------------------------------------------------------------
    sess11 = create_session(student_id="test_user")
    try:
        r11_1 = await handle_message("Who is the HOD of ECE?", student_id="test_user", session_id=sess11)
        assert "Raghuram" in r11_1.get("answer", "")

        r11_2 = await handle_message("Give me Physics Unit 1 notes", student_id="test_user", session_id=sess11)
        ans11_2 = r11_2.get("answer", "")
        act11_2 = r11_2.get("action_taken", "")
        cond11 = (
            act11_2 == "search_academic_documents"
            and "Physics" in ans11_2
            and "ECE" not in ans11_2
            and "Raghuram" not in ans11_2
        )
        assert_test(cond11, "Department HOD -> 'Give me Physics Unit 1 notes' remains strictly academic", f"act={act11_2}, ans={ans11_2}")
    finally:
        delete_session(sess11)

    # -------------------------------------------------------------------------
    # TEST 12: Where is CSE(AIML)? -> Who is the HOD of CSE? (Override context)
    # Explicit CSE must override CSE(AIML).
    # Expected: Dr. R. China Appala Naidu (NOT Dr. Siddesh G. M.)
    # -------------------------------------------------------------------------
    sess12 = create_session(student_id="test_user")
    try:
        r12_1 = await handle_message("Where is CSE(AIML)?", student_id="test_user", session_id=sess12)
        assert "Multipurpose" in r12_1.get("answer", "")

        r12_2 = await handle_message("Who is the HOD of CSE?", student_id="test_user", session_id=sess12)
        ans12_2 = r12_2.get("answer", "")
        print(f"Test 12 Ans: {ans12_2}")
        cond12 = "China Appala Naidu" in ans12_2 and "Siddesh" not in ans12_2
        assert_test(cond12, "Explicit CSE query overrides previous CSE(AIML) context", ans12_2)
    finally:
        delete_session(sess12)

    # -------------------------------------------------------------------------
    # TEST 13: ECE HOD -> "Where is that department?" -> "Who is its HOD?"
    # All three turns stay consistently connected to ECE.
    # -------------------------------------------------------------------------
    sess13 = create_session(student_id="test_user")
    try:
        r13_1 = await handle_message("Who is the HOD of ECE?", student_id="test_user", session_id=sess13)
        assert "Raghuram" in r13_1.get("answer", "")

        r13_2 = await handle_message("Where is that department?", student_id="test_user", session_id=sess13)
        assert "DES Block" in r13_2.get("answer", "")

        r13_3 = await handle_message("Who is its HOD?", student_id="test_user", session_id=sess13)
        ans13_3 = r13_3.get("answer", "")
        print(f"Test 13 Ans: {ans13_3}")
        cond13 = "Raghuram" in ans13_3 and "ECE" in ans13_3
        assert_test(cond13, "Three-turn chained follow-up maintains consistent ECE entity context", ans13_3)
    finally:
        delete_session(sess13)

    # -------------------------------------------------------------------------
    # TEST 14: Where is the principal's office? -> "What else is on that floor?"
    # Ground Floor Apex Block offices (Account Section, Scholarship Section, Registrar Office)
    # -------------------------------------------------------------------------
    sess14 = create_session(student_id="test_user")
    try:
        r14_1 = await handle_message("Where is the principal's office?", student_id="test_user", session_id=sess14)
        assert "Ground Floor" in r14_1.get("answer", "") and "Apex Block" in r14_1.get("answer", "")

        r14_2 = await handle_message("What else is on that floor?", student_id="test_user", session_id=sess14)
        ans14_2 = r14_2.get("answer", "")
        print(f"Test 14 Ans: {ans14_2}")
        cond14 = (
            "Account Section" in ans14_2
            and "Scholarship Section" in ans14_2
            and "Registrar" in ans14_2
            and "Apex Block" in ans14_2
        )
        assert_test(cond14, "Principal's office -> 'What else is on that floor?' returns Ground Floor Apex offices", ans14_2)
    finally:
        delete_session(sess14)

    # -------------------------------------------------------------------------
    # TEST 15: Who is the principal? -> "What is his email?"
    # Expected: principal@msrit.edu
    # -------------------------------------------------------------------------
    sess15 = create_session(student_id="test_user")
    try:
        r15_1 = await handle_message("Who is the principal of MSRIT?", student_id="test_user", session_id=sess15)
        assert "Sathish Babu" in r15_1.get("answer", "")

        r15_2 = await handle_message("What is his email?", student_id="test_user", session_id=sess15)
        ans15_2 = r15_2.get("answer", "")
        print(f"Test 15 Ans: {ans15_2}")
        cond15 = "principal@msrit.edu" in ans15_2
        assert_test(cond15, "Who is principal? -> 'What is his email?' returns principal@msrit.edu", ans15_2)
    finally:
        delete_session(sess15)

    print("\n" + "=" * 80)
    print(f"ALL {passed_tests} OF {total_tests} REGRESSION TESTS PASSED SUCCESSFULLY! [OK]")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_tests())
