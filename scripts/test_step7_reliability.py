"""
Step 7 Test Suite: Reliability and Demo-Hardening Pass

Tests:
1. Empty and whitespace-only user inputs fail safely with helpful guidance.
2. Unknown department returns truthful fallback without hallucination.
3. Unknown club returns truthful fallback without hallucination.
4. Unknown subject returns clean not-found message.
5. Invalid semester numbers are rejected safely.
6. Invalid CGPA numbers are rejected safely.
7. Invalid academic year numbers are rejected safely.
8. Invalid preference values (explanation_style, focus_subject) are rejected.
9. Missing document lookup returns clean None / honest message.
10. Missing student profile handled gracefully without crashes.
11. Malformed agentic tool-selection JSON is safely rejected.
12. Unknown MCP tool call returns controlled error dict without crashing.
13. Invalid MCP tool arguments return structured validation errors.
14. MAX_TOOL_CALLS = 3 is strictly enforced.
15. Inferred profile updates remain blocked in agentic loop.
16. AI&ML vs CSE(AI&ML) strict separation in HOD, location, and stream.
17. Qwen / Ollama failure in RAG falls back to verified document excerpts.
18. Qwen / Ollama failure in agentic synthesis falls back to verified DB facts.
19. Database lookup errors handled safely with fallback messages.
20. All operations record PostgreSQL audit logs.
21. Arbitrary code / tool execution is strictly prohibited and impossible.
"""
import asyncio
import sys
import json
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_connection
from backend.agent import classify_intent, handle_message, _extract_profile_data
from backend.agentic import (
    parse_tool_selection,
    run_agentic_workflow,
    is_explicit_profile_update_request,
    MAX_TOOL_CALLS,
    ALLOWED_TOOLS,
    _deterministic_synthesis_fallback
)
from backend.mcp_client import mcp_session, call_tool
from backend.memory import (
    get_student_profile,
    update_student_profile,
    delete_student_profile,
    normalize_canonical_branch
)
from backend.documents import get_academic_document, search_academic_documents
from backend.info_lookup import lookup_department, lookup_club
from backend.rag import answer_question, summarize_notes


TEST_STUDENT_ID = "test_step7_hardening_student"


async def setup_test_student():
    delete_student_profile(TEST_STUDENT_ID)
    update_student_profile(
        student_id=TEST_STUDENT_ID,
        name="Reliability Tester",
        college="MSRIT",
        degree="BE",
        branch="AI&ML",
        semester=1,
        year=1,
        cgpa=9.50
    )


async def cleanup_test_student():
    delete_student_profile(TEST_STUDENT_ID)


async def run_step7_tests():
    print("\n" + "=" * 70)
    print("RIT NEXUS — STEP 7: RELIABILITY & DEMO-HARDENING TEST SUITE")
    print("=" * 70)

    passed_count = 0
    total_tests = 21

    await setup_test_student()

    try:
        async with mcp_session():
            # -------------------------------------------------------------
            # TEST 1: Empty and whitespace-only user inputs
            # -------------------------------------------------------------
            print("\n[Test 1] Testing empty and whitespace-only user inputs...")
            res_empty = await handle_message("", student_id=TEST_STUDENT_ID)
            assert res_empty["action_taken"] == "empty_input"
            assert "Please enter a message" in res_empty["answer"]

            res_ws = await handle_message("   \t  \n  ", student_id=TEST_STUDENT_ID)
            assert res_ws["action_taken"] == "empty_input"
            assert "Please enter a message" in res_ws["answer"]

            res_empty_agentic = await handle_message("   ", student_id=TEST_STUDENT_ID, force_agentic=True)
            assert res_empty_agentic["action_taken"] == "empty_input"
            print("  [OK] Empty and whitespace inputs handled safely without crashes or LLM calls.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 2: Unknown department returns truthful fallback
            # -------------------------------------------------------------
            print("\n[Test 2] Testing unknown department handling...")
            res_unk_dept = await handle_message("Where is ZZZ department?", student_id=TEST_STUDENT_ID)
            assert "No department details found" in res_unk_dept["answer"]
            assert "ZZZ" in res_unk_dept["answer"]
            print("  [OK] Unknown department returns honest fallback without hallucination.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 3: Unknown club returns truthful fallback
            # -------------------------------------------------------------
            print("\n[Test 3] Testing unknown club handling...")
            res_unk_club = await handle_message("What does NonExistent club do?", student_id=TEST_STUDENT_ID)
            assert "No clubs found" in res_unk_club["answer"] or "No club details found" in res_unk_club["answer"]
            print("  [OK] Unknown club returns honest fallback without inventing club facts.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 4: Unknown subject returns clean not-found message
            # -------------------------------------------------------------
            print("\n[Test 4] Testing unknown subject resources query...")
            res_unk_subj = await handle_message("What academic resources are associated with Advanced Quantum Teleportation?", student_id=TEST_STUDENT_ID)
            assert "not currently available" in res_unk_subj["answer"].lower() or "not available" in res_unk_subj["answer"].lower()
            print("  [OK] Unknown subject resources query safely reports no documents.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 5: Invalid semester numbers are rejected safely
            # -------------------------------------------------------------
            print("\n[Test 5] Testing invalid semester numbers...")
            res_sem_high = await handle_message("Set my semester to 25", student_id=TEST_STUDENT_ID)
            assert "valid semester number between 1 and 10" in res_sem_high["answer"]

            res_sem_inv = await handle_message("update semester with abc", student_id=TEST_STUDENT_ID)
            assert "valid semester number" in res_sem_inv["answer"]
            print("  [OK] Invalid semester values rejected safely.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 6: Invalid CGPA values are rejected safely
            # -------------------------------------------------------------
            print("\n[Test 6] Testing invalid CGPA values...")
            res_cgpa_high = await handle_message("My CGPA is 15.5", student_id=TEST_STUDENT_ID)
            assert "numeric CGPA between 0.0 and 10.0" in res_cgpa_high["answer"]

            res_cgpa_inv = await handle_message("Set my CGPA to excellent", student_id=TEST_STUDENT_ID)
            assert "numeric CGPA between 0.0 and 10.0" in res_cgpa_inv["answer"]
            print("  [OK] Invalid CGPA values rejected safely.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 7: Invalid academic year values are rejected safely
            # -------------------------------------------------------------
            print("\n[Test 7] Testing invalid academic year values...")
            res_yr_high = await handle_message("Set my year to 9", student_id=TEST_STUDENT_ID)
            assert "academic year between 1 and 6" in res_yr_high["answer"]
            print("  [OK] Invalid year values rejected safely.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 8: Invalid preference values are rejected safely
            # -------------------------------------------------------------
            print("\n[Test 8] Testing invalid preference rejection...")
            res_pref_inv = await handle_message("Set my preference to ultra-fast", student_id=TEST_STUDENT_ID)
            assert "Invalid explanation style" in res_pref_inv["answer"]

            res_focus_inv = await handle_message("My main focus is Quantum Biology", student_id=TEST_STUDENT_ID)
            assert "Invalid focus subject" in res_focus_inv["answer"]
            print("  [OK] Invalid preference values rejected safely.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 9: Missing document lookup returns clean None
            # -------------------------------------------------------------
            print("\n[Test 9] Testing missing document lookup...")
            doc_none = get_academic_document("nonexistent-doc-id-999")
            assert doc_none is None

            docs_empty = search_academic_documents(subject="Quantum Teleportation", unit=99)
            assert isinstance(docs_empty, list) and len(docs_empty) == 0
            print("  [OK] Missing document returns clean None / empty list.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 10: Missing student profile handled gracefully
            # -------------------------------------------------------------
            print("\n[Test 10] Testing missing student profile handling...")
            prof_missing = get_student_profile("nonexistent_student_99999")
            assert prof_missing is None

            res_missing_std = await handle_message("What is my branch?", student_id="nonexistent_student_99999")
            assert "haven't set your profile yet" in res_missing_std["answer"].lower() or "don't have" in res_missing_std["answer"].lower()
            print("  [OK] Missing student profile handled gracefully.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 11: Malformed agentic tool-selection JSON
            # -------------------------------------------------------------
            print("\n[Test 11] Testing malformed agentic tool-selection JSON...")
            err_raw1 = parse_tool_selection("{ malformed: json without quotes }")
            assert err_raw1["action"] == "error"
            assert "Malformed" in err_raw1["error"]

            err_raw2 = parse_tool_selection("plain text without any json")
            assert err_raw2["action"] == "error"

            err_raw3 = parse_tool_selection('{"action": "invalid_action"}')
            assert err_raw3["action"] == "error"
            assert "Invalid action" in err_raw3["error"]

            err_raw4 = parse_tool_selection('{"action": "tool", "tool": "unregistered_tool"}')
            assert err_raw4["action"] == "error"
            assert "Unknown tool" in err_raw4["error"]

            err_raw5 = parse_tool_selection('{"action": "tool", "tool": "lookup_department", "arguments": "not-a-dict"}')
            assert err_raw5["action"] == "error"
            assert "dictionary" in err_raw5["error"]
            print("  [OK] All malformed tool selection variants rejected safely.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 12: Unknown MCP tool call returns controlled error dict
            # -------------------------------------------------------------
            print("\n[Test 12] Testing unknown MCP tool execution...")
            res_unk_tool = await call_tool("nonexistent_arbitrary_tool_xyz")
            assert isinstance(res_unk_tool, dict)
            assert "error" in res_unk_tool
            assert "Unknown tool" in res_unk_tool["error"]
            print("  [OK] Unknown tool safely blocked by MCP server.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 13: Invalid MCP tool arguments return validation errors
            # -------------------------------------------------------------
            print("\n[Test 13] Testing invalid MCP tool arguments...")
            res_bad_args = await call_tool("search_academic_documents", unit="not-an-integer-unit")
            assert isinstance(res_bad_args, dict)
            assert "error" in res_bad_args
            assert "validation error" in res_bad_args["error"].lower() or "unable to parse" in res_bad_args["error"].lower()
            print("  [OK] Invalid MCP argument types rejected with structured error.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 14: MAX_TOOL_CALLS = 3 is strictly enforced
            # -------------------------------------------------------------
            print("\n[Test 14] Testing MAX_TOOL_CALLS = 3 safety enforcement...")
            assert MAX_TOOL_CALLS == 3

            # Mock select_tool_agentic to attempt infinite tool calls
            call_counter = 0
            def infinite_tool_selector(query, student_id, observations):
                nonlocal call_counter
                call_counter += 1
                return {"action": "tool", "tool": "lookup_department", "arguments": {"query": "CSE"}}, 10.0

            with patch("backend.agentic.select_tool_agentic", side_effect=infinite_tool_selector):
                res_inf = await run_agentic_workflow("Multi-tool query", TEST_STUDENT_ID)
                # Must terminate after exactly MAX_TOOL_CALLS (3)
                assert res_inf["metrics"]["tool_call_count"] <= 3, f"Exceeded max tool calls: {res_inf['metrics']['tool_call_count']}"
                assert len(res_inf["tool_calls"]) <= 3
            print("  [OK] MAX_TOOL_CALLS = 3 strictly enforced in agentic loop.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 15: Inferred profile updates blocked in agentic loop
            # -------------------------------------------------------------
            print("\n[Test 15] Testing inferred profile update guardrail in agentic path...")
            # Query without explicit update command
            passive_query = "I think I should focus on Physics."
            assert is_explicit_profile_update_request(passive_query) is False

            # Model tries to update profile anyway
            def malicious_selector(query, student_id, observations):
                return {"action": "tool", "tool": "update_student_profile", "arguments": {"focus_subject": "Physics"}}, 5.0

            with patch("backend.agentic.select_tool_agentic", side_effect=malicious_selector):
                res_blocked = await run_agentic_workflow(passive_query, TEST_STUDENT_ID)
                # The profile update must have been blocked
                assert any("blocked" in str(tc.get("result", "")).lower() or "safety rule" in str(tc.get("result", "")).lower() for tc in res_blocked["tool_calls"])
            print("  [OK] Inferred profile update strictly blocked by agentic guardrail.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 16: AI&ML vs CSE(AI&ML) strict separation
            # -------------------------------------------------------------
            print("\n[Test 16] Testing AI&ML vs CSE(AI&ML) separation...")
            dept_aiml = lookup_department("AI&ML")
            dept_cse_aiml = lookup_department("CSE(AI&ML)")

            assert dept_aiml is not None and dept_cse_aiml is not None
            assert dept_aiml["code"] != dept_cse_aiml["code"]
            assert dept_aiml["hod_name"] != dept_cse_aiml["hod_name"]
            assert dept_aiml["location"] != dept_cse_aiml["location"]
            assert "Apex" in dept_aiml["location"]
            assert "Multipurpose" in dept_cse_aiml["location"]
            assert "Kallimani" in dept_aiml["hod_name"]
            assert "Siddesh" in dept_cse_aiml["hod_name"]
            print("  [OK] AI&ML and CSE(AI&ML) are strictly separated with verified distinct facts.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 17: Qwen failure in RAG falls back to verified excerpts
            # -------------------------------------------------------------
            print("\n[Test 17] Testing Qwen / Ollama failure fallback in RAG...")
            def mock_failing_post(*args, **kwargs):
                raise ConnectionError("Ollama service unreachable on port 11434")

            with patch("backend.rag.requests.post", side_effect=mock_failing_post):
                res_fallback = answer_question("Explain Laplace Transform", student_id=TEST_STUDENT_ID)
                # Must not crash, and should include verified notes excerpts
                assert res_fallback["answer"] is not None
                assert "verified excerpts" in res_fallback["answer"].lower() or len(res_fallback["sources"]) > 0

                res_sum_fallback = summarize_notes("Mathematics")
                assert res_sum_fallback["summary"] is not None
            print("  [OK] RAG safely falls back to verified excerpts when local LLM is unreachable.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 18: Qwen failure in agentic synthesis falls back to DB facts
            # -------------------------------------------------------------
            print("\n[Test 18] Testing Qwen failure fallback in agentic synthesis...")
            obs_sample = [
                {
                    "tool": "lookup_department",
                    "arguments": {"query": "CSE"},
                    "result": {"code": "CSE", "name": "Computer Science & Engineering", "hod_name": "Dr. R. China Appala Naidu", "location": "DES Block", "stream": "Computer Science & Engineering Stream"},
                    "success": True
                }
            ]
            fallback_synth = _deterministic_synthesis_fallback("Who heads CSE and where is it?", obs_sample)
            assert "Dr. R. China Appala Naidu" in fallback_synth
            assert "DES Block" in fallback_synth
            assert "Computer Science" in fallback_synth
            print("  [OK] Agentic synthesis fallback produces verified structured output.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 19: Database lookup error handling
            # -------------------------------------------------------------
            print("\n[Test 19] Testing database error resilience...")
            # If DB raises exception in lookup_department, it returns None safely
            with patch("backend.info_lookup.get_connection", side_effect=Exception("Database connection timeout")):
                res_db_err = lookup_department("CSE")
                assert res_db_err is None

            with patch("backend.documents.get_connection", side_effect=Exception("Database connection timeout")):
                res_doc_err = search_academic_documents(subject="Mathematics")
                assert res_doc_err == []
            print("  [OK] Database lookup failures handled safely without crashing callers.")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 20: PostgreSQL audit logging
            # -------------------------------------------------------------
            print("\n[Test 20] Verifying audit logging records all operations...")
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT tool_name, count(*) 
                FROM audit_log 
                WHERE student_id = %s 
                GROUP BY tool_name;
                """,
                (TEST_STUDENT_ID,)
            )
            audit_counts = dict(cur.fetchall())
            cur.close()
            conn.close()

            assert len(audit_counts) > 0, "No audit records found for test student"
            assert "empty_input" in audit_counts or "rag_answer_question" in audit_counts
            print(f"  [OK] Audit log verified with operations: {list(audit_counts.keys())}")
            passed_count += 1

            # -------------------------------------------------------------
            # TEST 21: Arbitrary tool execution is strictly prohibited
            # -------------------------------------------------------------
            print("\n[Test 21] Verifying arbitrary tool execution is impossible...")
            # Allowed tools is a strict, explicit set
            expected_allowed_tools = {
                "lookup_department",
                "lookup_club",
                "search_academic_documents",
                "get_academic_document",
                "get_student_profile",
                "update_student_profile",
                "get_academic_context",
                "get_recommended_clubs"
            }
            assert set(ALLOWED_TOOLS) == expected_allowed_tools, f"Tool registry mismatch: {ALLOWED_TOOLS}"
            # Attempting to call an arbitrary tool or shell command via MCP client is rejected
            res_sh = await call_tool("execute_shell_command", command="dir")
            assert "error" in res_sh
            assert "Unknown tool" in res_sh["error"]
            print("  [OK] Tool registry is strictly closed; arbitrary execution is impossible.")
            passed_count += 1

    finally:
        await cleanup_test_student()

    print("\n" + "=" * 70)
    print(f"STEP 7 RELIABILITY RESULT: {passed_count}/{total_tests} TESTS PASSED")
    print("=" * 70)
    assert passed_count == total_tests, f"Only {passed_count}/{total_tests} passed!"


if __name__ == "__main__":
    asyncio.run(run_step7_tests())
