"""
Step 4B Test Suite: Controlled Agentic Tool Selection for RIT NEXUS.
Verifies all 20 required agentic capabilities and regressions:
1. Simple department query
2. Simple club query
3. Simple academic document query
4. Student profile query
5. Combined memory + document query
6. Combined department + location query
7. Multi-tool query (at least 2 tools called)
8. Unknown request (safe response without hallucination)
9. Malformed model tool-selection output handling
10. Unknown tool requested by model handling
11. Tool execution failure handling
12. Maximum tool-call limit (caps at 3)
13. Explicit profile update allowed
14. Prevent inferred profile update (must block)
15. AI&ML vs CSE(AI&ML) distinction preserved
16. Audit log creation verification in PostgreSQL
17. Step 1 regression suite
18. Step 2 regression suite
19. Step 3 regression suite
20. Step 4A MCP tool regression suite
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import classify_intent, handle_message
from backend.agentic import (
    MAX_TOOL_CALLS,
    ALLOWED_TOOLS,
    parse_tool_selection,
    is_explicit_profile_update_request,
    run_agentic_workflow,
    select_tool_agentic,
    synthesize_grounded_answer
)
from backend import mcp_client
from backend.memory import (
    get_student_profile,
    update_student_profile,
    delete_student_profile
)
from db.connection import get_connection

TEST_STUDENT_ID = "test_agentic_student_999"


async def run_all_tests():
    print("=" * 80)
    print("RIT NEXUS — STEP 4B: CONTROLLED AGENTIC TOOL SELECTION TEST SUITE")
    print("=" * 80)
    suite_start = time.perf_counter()
    passed_tests = 0

    # Ensure clean state for test student
    delete_student_profile(TEST_STUDENT_ID)

    async with mcp_client.mcp_session():

        # =====================================================================
        # TEST 1: Simple Department Query
        # =====================================================================
        print("\n--- Test 1: Simple department query ---")
        t0 = time.perf_counter()
        res1 = await handle_message("Who is the HOD of CSE?", TEST_STUDENT_ID)
        dur1 = (time.perf_counter() - t0) * 1000
        assert "China Appala Naidu" in res1["answer"], f"Expected HOD in answer, got: {res1['answer']}"
        assert "metrics" in res1
        print(f"  [PASS] Answer: {res1['answer']}")
        print(f"  [METRICS] Total: {res1['metrics']['total_time_ms']}ms, Tool: {res1['metrics']['mcp_tool_time_ms']}ms, Router: {res1['metrics']['router_time_ms']}ms")
        passed_tests += 1

        # =====================================================================
        # TEST 2: Simple Club Query
        # =====================================================================
        print("\n--- Test 2: Simple club query ---")
        res2 = await handle_message("Tell me about CodeRIT club", TEST_STUDENT_ID)
        assert "CodeRIT" in res2["answer"], f"Expected CodeRIT in answer, got: {res2['answer']}"
        assert "metrics" in res2
        print(f"  [PASS] Answer: {res2['answer'][:120]}...")
        print(f"  [METRICS] Total: {res2['metrics']['total_time_ms']}ms, Tool: {res2['metrics']['mcp_tool_time_ms']}ms")
        passed_tests += 1

        # =====================================================================
        # TEST 3: Simple Academic Document Query
        # =====================================================================
        print("\n--- Test 3: Simple academic document query ---")
        res3 = await handle_message("Find Mathematics Unit 1 notes", TEST_STUDENT_ID)
        assert "Mathematics" in res3["answer"] or "Unit 1" in res3["answer"] or len(res3["sources"]) > 0
        assert "metrics" in res3
        print(f"  [PASS] Document retrieved with {len(res3['sources'])} source(s)")
        print(f"  [METRICS] Total: {res3['metrics']['total_time_ms']}ms, Tool: {res3['metrics']['mcp_tool_time_ms']}ms")
        passed_tests += 1

        # =====================================================================
        # TEST 4: Student Profile Query
        # =====================================================================
        print("\n--- Test 4: Student profile query ---")
        update_student_profile(
            student_id=TEST_STUDENT_ID,
            branch="ECE",
            semester=4,
            name="Rohan Sharma",
            cgpa=8.75
        )
        res4 = await handle_message("What branch am I in?", TEST_STUDENT_ID)
        assert "ECE" in res4["answer"], f"Expected ECE in profile answer, got: {res4['answer']}"
        assert "metrics" in res4
        print(f"  [PASS] Answer: {res4['answer']}")
        print(f"  [METRICS] Total: {res4['metrics']['total_time_ms']}ms, Tool: {res4['metrics']['mcp_tool_time_ms']}ms")
        passed_tests += 1

        # =====================================================================
        # TEST 5: Combined Memory + Document Query
        # =====================================================================
        print("\n--- Test 5: Combined memory + document query ---")
        res5 = await handle_message(
            "I'm a CSE(AI&ML) student in semester 3. What Mathematics material should I study?",
            TEST_STUDENT_ID
        )
        assert res5.get("answer"), "Expected non-empty answer"
        assert "metrics" in res5
        print(f"  [PASS] Multi-domain Answer: {res5['answer'][:150]}...")
        print(f"  [METRICS] Action: {res5.get('action_taken')}, Total: {res5['metrics']['total_time_ms']}ms")
        passed_tests += 1

        # =====================================================================
        # TEST 6: Combined Department + Location Query
        # =====================================================================
        print("\n--- Test 6: Combined department + location query ---")
        res6 = await handle_message("Who is the CSE HOD and where is the department?", TEST_STUDENT_ID)
        assert "China Appala Naidu" in res6["answer"], f"Missing HOD in answer: {res6['answer']}"
        assert "DES Block" in res6["answer"], f"Missing Location in answer: {res6['answer']}"
        print(f"  [PASS] Combined answer: {res6['answer']}")
        passed_tests += 1

        # =====================================================================
        # TEST 7: Multi-Tool Query (at least 2 tools called)
        # =====================================================================
        print("\n--- Test 7: Multi-tool query (at least 2 tools called) ---")
        # Run agentic workflow on query requiring both department and club lookup
        res7 = await run_agentic_workflow(
            "Tell me about CSE department and also CodeRIT club",
            TEST_STUDENT_ID
        )
        tool_names = [tc["tool"] for tc in res7.get("tool_calls", [])]
        print(f"  Executed tools: {tool_names}")
        assert len(res7.get("tool_calls", [])) >= 2, f"Expected >= 2 tool calls, got: {res7.get('tool_calls')}"
        assert "lookup_department" in tool_names
        assert "lookup_club" in tool_names
        assert "China Appala Naidu" in res7["answer"] or "CSE" in res7["answer"]
        assert "CodeRIT" in res7["answer"]
        print(f"  [PASS] Multi-tool answer: {res7['answer'][:140]}...")
        passed_tests += 1

        # =====================================================================
        # TEST 8: Unknown Request (safe response without hallucination)
        # =====================================================================
        print("\n--- Test 8: Unknown request (safe response without hallucination) ---")
        res8 = await handle_message("Who won the 2024 ICC T20 cricket world cup?", TEST_STUDENT_ID)
        assert "not sure" in res8["answer"].lower() or "can help with msrit" in res8["answer"].lower()
        print(f"  [PASS] Safe response: {res8['answer']}")
        passed_tests += 1

        # =====================================================================
        # TEST 9: Malformed Model Tool-Selection Output Handling
        # =====================================================================
        print("\n--- Test 9: Malformed model tool-selection output handling ---")
        # 1. Non-JSON string
        p1 = parse_tool_selection("I think you should use lookup_department")
        assert p1["action"] == "error", f"Expected action 'error', got {p1}"
        assert "Malformed" in p1["error"] or "JSON" in p1["error"] or "error" in p1

        # 2. Empty string
        p2 = parse_tool_selection("")
        assert p2["action"] == "error"

        # 3. Missing action field
        p3 = parse_tool_selection('{"tool": "lookup_department"}')
        assert p3["action"] == "error"
        assert "action" in p3["error"].lower()

        # 4. Safe recovery in run_agentic_workflow with simulated malformed model response
        with patch("backend.agentic.select_tool_agentic", return_value=({"action": "error", "error": "Simulated malformed JSON"}, 25.0)):
            res9 = await run_agentic_workflow("Where is CSE?", TEST_STUDENT_ID)
            assert res9["answer"], "Workflow should return a safe answer even on tool selection error"
            print(f"  [PASS] Safe fallback answer: {res9['answer']}")
        passed_tests += 1

        # =====================================================================
        # TEST 10: Unknown Tool Requested by Model Handling
        # =====================================================================
        print("\n--- Test 10: Unknown tool requested by model handling ---")
        # 1. parse_tool_selection validation
        p_unk = parse_tool_selection('{"action": "tool", "tool": "search_google_web", "arguments": {"query": "msrit"}}')
        assert p_unk["action"] == "error", f"Expected action 'error', got {p_unk}"
        assert "Unknown tool" in p_unk["error"] or "not recognized" in p_unk["error"]

        # 2. Workflow defense: Even if model somehow outputs unknown tool, workflow rejects it
        with patch("backend.agentic.select_tool_agentic", return_value=({"action": "tool", "tool": "unauthorized_cloud_api", "arguments": {}}, 15.0)):
            res10 = await run_agentic_workflow("Test query", TEST_STUDENT_ID)
            assert res10["answer"], "Workflow must return safe answer"
            print(f"  [PASS] Protected from unknown tool execution: {res10['answer']}")
        passed_tests += 1

        # =====================================================================
        # TEST 11: Tool Execution Failure Handling
        # =====================================================================
        print("\n--- Test 11: Tool execution failure handling ---")
        with patch("backend.mcp_client.call_tool", return_value={"error": "Database connection timeout"}):
            with patch("backend.agentic.select_tool_agentic", side_effect=[
                ({"action": "tool", "tool": "lookup_department", "arguments": {"query": "CSE"}}, 20.0),
                ({"action": "answer", "reason": "Stop after failure"}, 20.0)
            ]):
                res11 = await run_agentic_workflow("Who is HOD of CSE?", TEST_STUDENT_ID)
                assert res11["answer"], "Workflow must handle tool failure gracefully"
                assert len(res11["tool_calls"]) == 1
                assert res11["tool_calls"][0]["success"] is False
                print(f"  [PASS] Graceful failure handling: {res11['answer']}")
        passed_tests += 1

        # =====================================================================
        # TEST 12: Maximum Tool-Call Limit (Caps at 3)
        # =====================================================================
        print("\n--- Test 12: Maximum tool-call limit (caps at 3) ---")
        # Simulate a loop where model keeps asking to run lookup_department
        loop_response = ({"action": "tool", "tool": "lookup_department", "arguments": {"query": "CSE"}}, 10.0)
        with patch("backend.agentic.select_tool_agentic", return_value=loop_response):
            res12 = await run_agentic_workflow("Infinite loop test query", TEST_STUDENT_ID)
            call_count = len(res12["tool_calls"])
            assert call_count == MAX_TOOL_CALLS, f"Expected exactly {MAX_TOOL_CALLS} tool calls, got {call_count}"
            assert res12["metrics"]["tool_call_count"] == MAX_TOOL_CALLS
            print(f"  [PASS] Workflow strictly halted at MAX_TOOL_CALLS = {call_count}")
        passed_tests += 1

        # =====================================================================
        # TEST 13: Explicit Profile Update Allowed
        # =====================================================================
        print("\n--- Test 13: Explicit profile update allowed ---")
        assert is_explicit_profile_update_request("Update my branch with ECE") is True
        assert is_explicit_profile_update_request("set semester to 5") is True
        assert is_explicit_profile_update_request("my CGPA is 9.15") is True

        res13 = await handle_message("update my branch with ECE", TEST_STUDENT_ID)
        assert "Profile updated successfully" in res13["answer"] or "ECE" in res13["answer"]
        prof13 = get_student_profile(TEST_STUDENT_ID)
        assert prof13["branch"] == "ECE"
        print(f"  [PASS] Explicit profile update verified: branch = {prof13['branch']}")
        passed_tests += 1

        # =====================================================================
        # TEST 14: Prevent Inferred Profile Update (Must Block)
        # =====================================================================
        print("\n--- Test 14: Prevent inferred profile update (must block) ---")
        assert is_explicit_profile_update_request("Where is the ECE department?") is False
        assert is_explicit_profile_update_request("Who is the HOD of Mechanical Engineering?") is False
        assert is_explicit_profile_update_request("Tell me about CodeRIT") is False

        # Set profile to known state
        update_student_profile(student_id=TEST_STUDENT_ID, branch="ECE")

        # Simulate model attempting to update profile when user only asked a question
        with patch("backend.agentic.select_tool_agentic", return_value=({
            "action": "tool",
            "tool": "update_student_profile",
            "arguments": {"branch": "ME"}
        }, 15.0)):
            res14 = await run_agentic_workflow("Where is the ME department?", TEST_STUDENT_ID)
            # Verify update was blocked
            prof14 = get_student_profile(TEST_STUDENT_ID)
            assert prof14["branch"] == "ECE", f"Safety violation: Profile was modified to {prof14['branch']}"
            assert any("Profile update blocked" in obs.get("error", "") for obs in res14["observations"])
            print(f"  [PASS] Blocked inferred profile update. Branch remains '{prof14['branch']}'.")
        passed_tests += 1

        # =====================================================================
        # TEST 15: AI&ML vs CSE(AI&ML) Distinction Preserved
        # =====================================================================
        print("\n--- Test 15: AI&ML vs CSE(AI&ML) distinction preserved ---")
        aiml_dept = await mcp_client.call_tool("lookup_department", query="AI&ML")
        assert "Apex Block" in aiml_dept["location"], f"Expected Apex Block, got: {aiml_dept['location']}"
        assert "Jagadish" in aiml_dept["hod_name"]

        cse_aiml_dept = await mcp_client.call_tool("lookup_department", query="CSE(AI&ML)")
        assert "Multipurpose Block" in cse_aiml_dept["location"], f"Expected Multipurpose Block, got: {cse_aiml_dept['location']}"
        assert "Siddesh" in cse_aiml_dept["hod_name"]

        print(f"  [PASS] AI&ML: {aiml_dept['location']} | HOD: {aiml_dept['hod_name']}")
        print(f"  [PASS] CSE(AI&ML): {cse_aiml_dept['location']} | HOD: {cse_aiml_dept['hod_name']}")
        passed_tests += 1

        # =====================================================================
        # TEST 16: Audit Log Creation Verification in PostgreSQL
        # =====================================================================
        print("\n--- Test 16: Audit log creation verification in PostgreSQL ---")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tool_name, student_id, success, parameters FROM audit_log WHERE student_id = %s ORDER BY id DESC LIMIT 5",
                    (TEST_STUDENT_ID,)
                )
                rows = cur.fetchall()
                assert len(rows) > 0, "No audit log entries recorded for test student"
                print(f"  Found {len(rows)} recent audit log entries for {TEST_STUDENT_ID}:")
                for r in rows:
                    print(f"    - Tool: {r[0]}, Success: {r[2]}")
        print("  [PASS] PostgreSQL audit logging verified")
        passed_tests += 1

        # Clean up test student
        delete_student_profile(TEST_STUDENT_ID)

        # =====================================================================
        # TEST 17: Step 1 Regression Suite
        # =====================================================================
        print("\n--- Test 17: Step 1 regression suite ---")
        import scripts.test_department_responses as step1_tests
        await step1_tests.run_tests()
        print("  [PASS] Step 1 regression suite passed")
        passed_tests += 1

        # =====================================================================
        # TEST 18: Step 2 Regression Suite
        # =====================================================================
        print("\n--- Test 18: Step 2 regression suite ---")
        import scripts.test_academic_documents as step2_tests
        await step2_tests.main()
        print("  [PASS] Step 2 regression suite passed")
        passed_tests += 1

        # =====================================================================
        # TEST 19: Step 3 Regression Suite
        # =====================================================================
        print("\n--- Test 19: Step 3 regression suite ---")
        import scripts.test_student_memory as step3_tests
        await step3_tests.test_intents()
        step3_tests.test_extraction()
        step3_tests.test_canonical_branch_normalization()
        await step3_tests.test_persistence_and_safe_partial_updates()
        await step3_tests.test_identity_and_field_query_variants()
        print("  [PASS] Step 3 regression suite passed")
        passed_tests += 1

        # =====================================================================
        # TEST 20: Step 4A MCP Tool Regression Suite
        # =====================================================================
        print("\n--- Test 20: Step 4A MCP tool regression suite ---")
        import scripts.test_mcp_tools as step4a_tests
        await step4a_tests.run_mcp_tests()
        print("  [PASS] Step 4A MCP tool regression suite passed")
        passed_tests += 1

        # =====================================================================
        # TEST 21: Deterministic department query does not invoke agentic Qwen
        # =====================================================================
        print("\n--- Test 21: Deterministic department query does not invoke agentic Qwen ---")
        with patch("backend.agentic.select_tool_agentic", side_effect=AssertionError("select_tool_agentic must NOT be invoked for deterministic department query")):
            res21 = await handle_message("Who is the HOD of CSE?", TEST_STUDENT_ID)
            assert "China Appala Naidu" in res21["answer"]
            assert res21["metrics"]["agent_selection_ms"] == 0.0
            assert res21["metrics"]["tool_call_count"] == 1
            assert res21["metrics"]["qwen_call_count"] == 1  # Exactly 1 grounded synthesis call
            print(f"  [PASS] Agentic Qwen bypassed, synthesis called once (metrics: {res21['metrics']})")
        passed_tests += 1

        # =====================================================================
        # TEST 22: Deterministic club query does not invoke agentic Qwen
        # =====================================================================
        print("\n--- Test 22: Deterministic club query does not invoke agentic Qwen ---")
        with patch("backend.agentic.select_tool_agentic", side_effect=AssertionError("select_tool_agentic must NOT be invoked for deterministic club query")):
            res22 = await handle_message("What clubs are available?", TEST_STUDENT_ID)
            assert "Student Clubs" in res22["answer"] or "CodeRIT" in res22["answer"]
            assert res22["metrics"]["agent_selection_ms"] == 0.0
            assert res22["metrics"]["tool_call_count"] == 1
            assert res22["metrics"]["qwen_call_count"] == 0  # Structured response, 0 Qwen calls
            print(f"  [PASS] Club handled deterministically with 0 Qwen calls (metrics: {res22['metrics']})")
        passed_tests += 1

        # =====================================================================
        # TEST 23: Deterministic document query does not invoke agentic Qwen
        # =====================================================================
        print("\n--- Test 23: Deterministic document query does not invoke agentic Qwen ---")
        with patch("backend.agentic.select_tool_agentic", side_effect=AssertionError("select_tool_agentic must NOT be invoked for deterministic document query")):
            res23 = await handle_message("Find Mathematics Unit 1 notes", TEST_STUDENT_ID)
            assert "Mathematics" in res23["answer"] or len(res23["sources"]) > 0
            assert res23["metrics"]["agent_selection_ms"] == 0.0
            assert res23["metrics"]["tool_call_count"] == 1
            assert res23["metrics"]["qwen_call_count"] == 0  # Structured response, 0 Qwen calls
            print(f"  [PASS] Document handled deterministically with 0 Qwen calls (metrics: {res23['metrics']})")
        passed_tests += 1

        # =====================================================================
        # TEST 24: Simple profile query does not invoke agentic Qwen
        # =====================================================================
        print("\n--- Test 24: Simple profile query does not invoke agentic Qwen ---")
        update_student_profile(student_id=TEST_STUDENT_ID, branch="CSE", semester=3, name="Vishal")
        with patch("backend.agentic.select_tool_agentic", side_effect=AssertionError("select_tool_agentic must NOT be invoked for simple profile query")):
            res24_1 = await handle_message("Who am I?", TEST_STUDENT_ID)
            assert "Vishal" in res24_1["answer"]
            assert res24_1["metrics"]["agent_selection_ms"] == 0.0
            assert res24_1["metrics"]["qwen_call_count"] == 0

            res24_2 = await handle_message("What branch am I in?", TEST_STUDENT_ID)
            assert "CSE" in res24_2["answer"]
            assert res24_2["metrics"]["agent_selection_ms"] == 0.0
            assert res24_2["metrics"]["qwen_call_count"] == 0
            print(f"  [PASS] Profile queries handled deterministically with 0 Qwen calls")
        passed_tests += 1

        # =====================================================================
        # TEST 25: Multi-tool deterministic sequence bypasses Qwen tool selection
        # =====================================================================
        print("\n--- Test 25: Multi-tool deterministic sequence bypasses Qwen tool selection ---")
        with patch("backend.agentic.select_tool_agentic", side_effect=AssertionError("select_tool_agentic must NOT be invoked for planned multi-tool sequence")):
            res25 = await run_agentic_workflow("Tell me about CSE department and also CodeRIT club", TEST_STUDENT_ID)
            assert len(res25["tool_calls"]) == 2
            t_names = [tc["tool"] for tc in res25["tool_calls"]]
            assert "lookup_department" in t_names
            assert "lookup_club" in t_names
            assert res25["metrics"]["agent_selection_ms"] == 0.0
            assert res25["metrics"]["tool_call_count"] == 2
            assert res25["metrics"]["tool_call_count"] <= 3
            assert res25["metrics"]["qwen_call_count"] == 1  # Exactly 1 final synthesis call
            print(f"  [PASS] Multi-tool sequence executed directly (calls: {res25['metrics']['tool_call_count']}, qwen calls: {res25['metrics']['qwen_call_count']})")
        passed_tests += 1

        # =====================================================================
        # TEST 26: Genuine multi-domain advisory query preserves agentic reasoning
        # =====================================================================
        print("\n--- Test 26: Genuine multi-domain advisory query preserves agentic reasoning ---")
        from backend.agentic import plan_deterministic_tool_sequence
        ambig_q = "I'm a semester 3 CSE(AI&ML) student. What Mathematics material should I study?"
        assert plan_deterministic_tool_sequence(ambig_q) is None, "Ambiguous/advisory query must not be deterministically hardcoded"
        intent26 = classify_intent(ambig_q)
        assert intent26["type"] == "agentic", f"Expected intent 'agentic', got: {intent26}"
        print("  [PASS] Advisory/combined query preserves agentic reasoning path")
        passed_tests += 1

        # =====================================================================
        # TEST 27: Timing Instrumentation Verification
        # =====================================================================
        print("\n--- Test 27: Timing instrumentation verification ---")
        res27 = await handle_message("What clubs are available?", TEST_STUDENT_ID)
        m27 = res27["metrics"]
        required_metrics = [
            "router_ms",
            "agent_selection_ms",
            "tool_execution_ms",
            "synthesis_ms",
            "total_ms",
            "tool_call_count",
            "qwen_call_count"
        ]
        for rm in required_metrics:
            assert rm in m27, f"Missing required metric: {rm}"
            assert isinstance(m27[rm], (int, float)), f"Metric {rm} must be numeric"
        print(f"  [PASS] All 7 required timing metrics present: { {k: m27[k] for k in required_metrics} }")
        passed_tests += 1

    total_dur = round(time.perf_counter() - suite_start, 2)
    print("\n" + "=" * 80)
    print(f"ALL {passed_tests} STEP 4B AGENTIC, OPTIMIZATION & REGRESSION TESTS PASSED! ({passed_tests}/{passed_tests} in {total_dur}s)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
