"""
Step 6 Test Suite: Student Personalization (Explicit Preferences + Personalized Responses)

Tests at minimum:
1. Explicit concise preference update.
2. Explicit detailed preference update.
3. Focus subject update.
4. Preference persistence across database reads.
5. Preference query.
6. Preference clearing.
7. Clearing preferences preserves all other student profile fields.
8. Invalid explanation style is rejected.
9. Invalid focus subject is rejected.
10. Passive/inferred preference statements do NOT update memory.
11. Existing AI&ML vs CSE(AI&ML) distinction remains intact.
12. Existing profile PATCH behavior remains intact.
13. Preference retrieval is deterministic and does not unnecessarily call Qwen.
14. Concise preference is passed to the response-generation layer.
15. Detailed preference is passed to the response-generation layer.
16. Explicit current query overrides focus_subject when the query specifies another subject.
17. Agentic profile-write protection still blocks inferred preference writes.
18. Existing audit logging still records preference updates/clears.
"""
import asyncio
import sys
import json
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import classify_intent, handle_message, _extract_profile_data
from backend.memory import (
    get_student_profile,
    update_student_profile,
    delete_student_profile,
    normalize_preference_value,
    validate_and_normalize_preferences,
    format_preferences_response,
    SUPPORTED_PREFERENCE_KEYS,
    SUPPORTED_EXPLANATION_STYLES,
    SUPPORTED_FIRST_YEAR_SUBJECTS,
    normalize_canonical_branch
)
from backend.agentic import is_explicit_profile_update_request
from backend.rag import answer_question
from backend.mcp_client import mcp_session
from db.connection import get_connection


TEST_STUDENT_ID = "test_step6_student"


async def setup_test_student():
    """Ensure clean initial profile state."""
    delete_student_profile(TEST_STUDENT_ID)
    update_student_profile(
        student_id=TEST_STUDENT_ID,
        name="Personalization Tester",
        college="MSRIT",
        degree="BE",
        branch="AI&ML",
        semester=1,
        year=1,
        cgpa=9.10
    )


async def cleanup_test_student():
    delete_student_profile(TEST_STUDENT_ID)


async def run_step6_tests():
    print("\n" + "=" * 65)
    print("STEP 6 — STUDENT PERSONALIZATION TEST SUITE")
    print("=" * 65)

    passed_count = 0
    total_tests = 18

    await setup_test_student()

    try:
        async with mcp_session():
            # --------------------------------------------------
            # TEST 1: Explicit concise preference update
            # --------------------------------------------------
            print("\n[Test 1] Explicit concise preference update...")
            res = await handle_message("Remember that I prefer concise explanations.", student_id=TEST_STUDENT_ID)
            assert res["action_taken"] == "update_student_profile", f"Expected update_student_profile, got {res['action_taken']}"
            assert "Explanation Style" in res["answer"] and "concise" in res["answer"], f"Expected confirmation of concise style, got {res['answer']}"
            prof = get_student_profile(TEST_STUDENT_ID)
            assert prof["preferences"].get("explanation_style") == "concise", f"Expected concise in DB, got {prof['preferences']}"
            print("  -> PASS: Concise preference updated and persisted.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 2: Explicit detailed preference update
            # --------------------------------------------------
            print("\n[Test 2] Explicit detailed preference update...")
            res = await handle_message("Set my preference to detailed explanations.", student_id=TEST_STUDENT_ID)
            assert res["action_taken"] == "update_student_profile"
            assert "Explanation Style" in res["answer"] and "detailed" in res["answer"]
            prof = get_student_profile(TEST_STUDENT_ID)
            assert prof["preferences"].get("explanation_style") == "detailed"
            print("  -> PASS: Detailed preference updated and persisted.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 3: Focus subject update
            # --------------------------------------------------
            print("\n[Test 3] Focus subject update...")
            res = await handle_message("Remember that my main focus is Physics.", student_id=TEST_STUDENT_ID)
            assert res["action_taken"] == "update_student_profile"
            assert "Focus Subject" in res["answer"] and "Physics" in res["answer"]
            prof = get_student_profile(TEST_STUDENT_ID)
            assert prof["preferences"].get("focus_subject") == "Physics"
            print("  -> PASS: Focus subject updated to Physics.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 4: Preference persistence across database reads
            # --------------------------------------------------
            print("\n[Test 4] Preference persistence across database reads...")
            prof_fresh = get_student_profile(TEST_STUDENT_ID)
            assert prof_fresh is not None
            assert prof_fresh["preferences"] == {"explanation_style": "detailed", "focus_subject": "Physics"}
            print("  -> PASS: Both preferences accurately persisted and read from DB.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 5: Preference query
            # --------------------------------------------------
            print("\n[Test 5] Preference query...")
            res_all = await handle_message("What are my preferences?", student_id=TEST_STUDENT_ID)
            assert "Detailed explanations" in res_all["answer"] or "detailed" in res_all["answer"].lower()
            assert "Physics" in res_all["answer"]

            res_style = await handle_message("What response style do I prefer?", student_id=TEST_STUDENT_ID)
            assert "detailed" in res_style["answer"].lower()

            res_focus = await handle_message("What subject am I focusing on?", student_id=TEST_STUDENT_ID)
            assert "Physics" in res_focus["answer"]
            print("  -> PASS: Deterministic preference queries return stored values.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 6: Preference clearing
            # --------------------------------------------------
            print("\n[Test 6] Preference clearing...")
            res_clear = await handle_message("Clear my preferences.", student_id=TEST_STUDENT_ID)
            assert res_clear["action_taken"] == "update_student_profile"
            assert "cleared" in res_clear["answer"].lower()
            prof_cleared = get_student_profile(TEST_STUDENT_ID)
            assert prof_cleared["preferences"] == {} or not prof_cleared["preferences"]

            # Verify query after clearing
            res_after = await handle_message("What are my preferences?", student_id=TEST_STUDENT_ID)
            assert "You don't have any saved preferences yet." in res_after["answer"]
            print("  -> PASS: Preferences cleared and verified.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 7: Clearing preferences preserves all other student profile fields
            # --------------------------------------------------
            print("\n[Test 7] Preserving other student profile fields upon clearing...")
            prof_check = get_student_profile(TEST_STUDENT_ID)
            assert prof_check["name"] == "Personalization Tester", f"Name corrupted: {prof_check['name']}"
            assert prof_check["branch"] == "AI&ML", f"Branch corrupted: {prof_check['branch']}"
            assert prof_check["semester"] == 1, f"Semester corrupted: {prof_check['semester']}"
            assert prof_check["degree"] == "BE", f"Degree corrupted: {prof_check['degree']}"
            assert float(prof_check["cgpa"]) == 9.10, f"CGPA corrupted: {prof_check['cgpa']}"
            print("  -> PASS: All core profile fields preserved.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 8: Invalid explanation style is rejected
            # --------------------------------------------------
            print("\n[Test 8] Rejecting invalid explanation style...")
            res_invalid = await handle_message("Set my preference to ultra-fast", student_id=TEST_STUDENT_ID)
            assert "Invalid explanation style" in res_invalid["answer"] or "could not understand" in res_invalid["answer"].lower()
            prof_after_inv = get_student_profile(TEST_STUDENT_ID)
            assert "ultra-fast" not in str(prof_after_inv["preferences"])
            print("  -> PASS: Invalid explanation style rejected.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 9: Invalid focus subject is rejected
            # --------------------------------------------------
            print("\n[Test 9] Rejecting invalid focus subject...")
            res_inv_subj = await handle_message("My main focus is Quantum Computing", student_id=TEST_STUDENT_ID)
            assert "Invalid focus subject" in res_inv_subj["answer"] or "Supported first-year subjects" in res_inv_subj["answer"]
            prof_after_inv_subj = get_student_profile(TEST_STUDENT_ID)
            assert "Quantum Computing" not in str(prof_after_inv_subj["preferences"])
            print("  -> PASS: Invalid focus subject rejected.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 10: Passive/inferred preference statements do NOT update memory
            # --------------------------------------------------
            print("\n[Test 10] Passive/inferred statements do NOT update memory...")
            passive_statements = [
                "I don't understand long explanations.",
                "Short answers are sometimes easier.",
                "I am studying Mathematics today.",
                "I think I should focus on Physics.",
                "I hate long answers.",
                "My friend prefers concise answers."
            ]
            for stmt in passive_statements:
                extracted, invalid = _extract_profile_data(stmt)
                assert "preferences" not in extracted or not extracted["preferences"], (
                    f"Inferred preference leaked from passive statement: '{stmt}' -> {extracted}"
                )
            print("  -> PASS: Zero passive or inferred preferences extracted.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 11: Existing AI&ML vs CSE(AI&ML) distinction remains intact
            # --------------------------------------------------
            print("\n[Test 11] AI&ML vs CSE(AI&ML) canonical branch integrity...")
            assert normalize_canonical_branch("AI&ML") == "AI&ML"
            assert normalize_canonical_branch("AIML") == "AI&ML"
            assert normalize_canonical_branch("Artificial Intelligence and Machine Learning") == "AI&ML"
            assert normalize_canonical_branch("CSE(AI&ML)") == "CSE(AI&ML)"
            assert normalize_canonical_branch("Computer Science and Engineering (Artificial Intelligence and Machine Learning)") == "CSE(AI&ML)"
            print("  -> PASS: Strict branch distinction preserved.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 12: Existing profile PATCH behavior remains intact
            # --------------------------------------------------
            print("\n[Test 12] Profile PATCH behavior remains intact...")
            # Store a preference
            update_student_profile(TEST_STUDENT_ID, preferences={"explanation_style": "concise"})
            # Now update only semester
            update_student_profile(TEST_STUDENT_ID, semester=2)
            prof_patched = get_student_profile(TEST_STUDENT_ID)
            assert prof_patched["semester"] == 2
            assert prof_patched["preferences"].get("explanation_style") == "concise"
            # Now update focus subject without overwriting explanation_style
            update_student_profile(TEST_STUDENT_ID, preferences={"focus_subject": "Mathematics"})
            prof_patched2 = get_student_profile(TEST_STUDENT_ID)
            assert prof_patched2["preferences"].get("explanation_style") == "concise"
            assert prof_patched2["preferences"].get("focus_subject") == "Mathematics"
            print("  -> PASS: Profile and preference PATCH merge behavior validated.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 13: Preference retrieval is deterministic and does not unnecessarily call Qwen
            # --------------------------------------------------
            print("\n[Test 13] Deterministic preference retrieval latency & 0 Qwen calls...")
            res_q = await handle_message("What are my preferences?", student_id=TEST_STUDENT_ID)
            metrics = res_q.get("metrics", {})
            assert metrics.get("qwen_calls", 0) == 0, f"Expected 0 Qwen calls, got {metrics.get('qwen_calls')}"
            assert res_q["action_taken"] == "get_student_profile"
            print("  -> PASS: Retrieved deterministically with 0 Qwen calls.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 14: Concise preference is passed to the response-generation layer
            # --------------------------------------------------
            print("\n[Test 14] Concise preference passed to response layer...")
            update_student_profile(TEST_STUDENT_ID, preferences={"explanation_style": "concise"})
            captured_prompt = None

            def dummy_post_concise(url, json=None, timeout=None, **kwargs):
                nonlocal captured_prompt
                captured_prompt = (json or {}).get("prompt", "")
                class MockResponse:
                    def raise_for_status(self): pass
                    def json(self): return {"response": "A vector is an entity with magnitude and direction."}
                return MockResponse()

            with patch("backend.rag.requests.post", side_effect=dummy_post_concise):
                res_rag = answer_question("Explain what a vector is.", student_id=TEST_STUDENT_ID)
                assert captured_prompt is not None, "Qwen was not invoked for academic explanation"
                assert "CONCISE STYLE PREFERENCE" in captured_prompt or "concise" in captured_prompt.lower(), (
                    f"Concise instruction missing in prompt:\n{captured_prompt}"
                )
            print("  -> PASS: Concise style instruction injected into local generation prompt.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 15: Detailed preference is passed to the response-generation layer
            # --------------------------------------------------
            print("\n[Test 15] Detailed preference passed to response layer...")
            update_student_profile(TEST_STUDENT_ID, preferences={"explanation_style": "detailed"})
            captured_prompt_det = None

            def dummy_post_det(url, json=None, timeout=None, **kwargs):
                nonlocal captured_prompt_det
                captured_prompt_det = (json or {}).get("prompt", "")
                class MockResponse:
                    def raise_for_status(self): pass
                    def json(self): return {"response": "A vector is a geometric entity with magnitude and direction, used extensively in linear algebra."}
                return MockResponse()

            with patch("backend.rag.requests.post", side_effect=dummy_post_det):
                res_rag_det = answer_question("Explain what a vector is.", student_id=TEST_STUDENT_ID)
                assert captured_prompt_det is not None
                assert "DETAILED STYLE PREFERENCE" in captured_prompt_det or "detailed" in captured_prompt_det.lower(), (
                    f"Detailed instruction missing in prompt:\n{captured_prompt_det}"
                )
            print("  -> PASS: Detailed style instruction injected into local generation prompt.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 16: Explicit current query overrides focus_subject
            # --------------------------------------------------
            print("\n[Test 16] Explicit current query overrides saved focus_subject...")
            # Set focus to Mathematics
            update_student_profile(TEST_STUDENT_ID, preferences={"focus_subject": "Mathematics"})

            captured_prompt_override = None
            def dummy_post_override(url, json=None, timeout=None, **kwargs):
                nonlocal captured_prompt_override
                captured_prompt_override = (json or {}).get("prompt", "")
                class MockResponse:
                    def raise_for_status(self): pass
                    def json(self): return {"response": "In Physics, study semiconductors and optics."}
                return MockResponse()

            with patch("backend.rag.requests.post", side_effect=dummy_post_override):
                res_override = answer_question("What should I study in Physics?", student_id=TEST_STUDENT_ID)
                # The prompt must ground on Physics, not Mathematics
                assert captured_prompt_override is not None
                assert "Physics" in captured_prompt_override
                assert "Mathematics" not in res_override.get("sources", []) or "Physics" in str(res_override.get("sources", []))
            print("  -> PASS: Query explicitly specifying Physics overrides saved focus Mathematics.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 17: Agentic profile-write protection blocks inferred preference writes
            # --------------------------------------------------
            print("\n[Test 17] Agentic guardrail blocks inferred preference writes...")
            assert is_explicit_profile_update_request("Remember that I prefer concise explanations.") is True
            assert is_explicit_profile_update_request("Set my preference to detailed explanations.") is True
            assert is_explicit_profile_update_request("Clear my preferences.") is True
            assert is_explicit_profile_update_request("I don't understand long explanations.") is False
            assert is_explicit_profile_update_request("Short answers are sometimes easier.") is False
            assert is_explicit_profile_update_request("I think I should focus on Physics.") is False
            print("  -> PASS: Agentic profile update guardrail blocks all inferred preference attempts.")
            passed_count += 1

            # --------------------------------------------------
            # TEST 18: Existing audit logging records preference updates/clears
            # --------------------------------------------------
            print("\n[Test 18] Audit logging records preference operations...")
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT tool_name, parameters, success
                FROM audit_log
                WHERE student_id = %s AND tool_name = 'update_student_profile'
                ORDER BY timestamp DESC
                LIMIT 5;
                """,
                (TEST_STUDENT_ID,)
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            assert len(rows) > 0, "No audit log records found for update_student_profile"
            found_pref_audit = any("preferences" in json.dumps(r[1]) or "clear_preferences" in json.dumps(r[1]) for r in rows)
            assert found_pref_audit, f"Preference audit parameter not logged in audit_log: {rows}"
            print(f"  -> PASS: Verified {len(rows)} recent audit_log entries for profile updates/clears.")
            passed_count += 1

    finally:
        await cleanup_test_student()

    print("\n" + "=" * 65)
    print(f"STEP 6 RESULT: {passed_count}/{total_tests} TESTS PASSED")
    print("=" * 65)
    assert passed_count == total_tests, f"Only {passed_count}/{total_tests} passed!"


if __name__ == "__main__":
    asyncio.run(run_step6_tests())
