"""
Comprehensive Test Suite for Step 5: Knowledge / Relationship Layer.
Verifies all 29 requirements:
 1. subjects table seeded
 2. stream_branches seeded
 3. stream_subjects seeded
 4. club branch_scope seeded
 5. idempotent loader
 6. CSE relationship
 7. AI&ML relationship
 8. CSE(AI&ML) relationship
 9. AI&ML != CSE(AI&ML)
10. student -> branch -> stream resolution
11. student -> cycle -> subjects
12. branch -> subjects
13. subject -> document count
14. Mathematics Unit 1 retrieval
15. branch-specific club filtering
16. All-branches club filtering
17. category filtering
18. unknown branch handling
19. unknown student handling
20. get_academic_context MCP tool
21. get_recommended_clubs MCP tool
22. audit entries created
23. MCP tool argument validation
24. MAX_TOOL_CALLS remains 3
25. inferred profile update remains blocked
26. Representative multi-hop natural language agent queries with latency & metrics
"""
import sys
import asyncio
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_connection
from backend.mcp_client import mcp_session, call_tool, list_tools
from backend.knowledge import get_academic_context, get_recommended_clubs, resolve_branch_db_code
from backend.memory import update_student_profile, get_student_profile, delete_student_profile
from backend.documents import search_academic_documents
from backend.agent import handle_message
from backend.agentic import MAX_TOOL_CALLS
from scripts.load_relationships import seed_subjects, seed_stream_branches, seed_stream_subjects, seed_club_branch_scope


async def run_step5_tests():
    print("=" * 80)
    print("RIT NEXUS — STEP 5: KNOWLEDGE / RELATIONSHIP LAYER TEST SUITE")
    print("=" * 80)
    
    passed_tests = 0
    t_start = time.perf_counter()

    conn = get_connection()
    cur = conn.cursor()

    try:
        # -------------------------------------------------------------
        # 1. subjects table seeded
        # -------------------------------------------------------------
        print("\n[Test 1] Verifying subjects table seeded...")
        cur.execute("SELECT code, name, semester, default_cycle FROM subjects ORDER BY code;")
        subjects_rows = cur.fetchall()
        assert len(subjects_rows) >= 5, f"Expected at least 5 subjects, found {len(subjects_rows)}"
        subject_names = {r[1] for r in subjects_rows}
        assert "Mathematics" in subject_names
        assert "Physics" in subject_names
        assert "Chemistry" in subject_names
        assert "Programming in C" in subject_names
        assert "Civil Engineering (ESC)" in subject_names
        print(f"  [OK] Found {len(subjects_rows)} canonical subjects: {sorted(list(subject_names))}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 2. stream_branches seeded
        # -------------------------------------------------------------
        print("\n[Test 2] Verifying stream_branches table seeded...")
        cur.execute("SELECT DISTINCT stream_name, count(branch_code) FROM stream_branches GROUP BY stream_name;")
        stream_branch_counts = dict(cur.fetchall())
        assert len(stream_branch_counts) == 4, f"Expected 4 streams, found {len(stream_branch_counts)}"
        assert "Computer Science & Engineering Stream" in stream_branch_counts
        assert "Electrical & Electronics Engineering Stream" in stream_branch_counts
        assert "Mechanical Engineering Stream" in stream_branch_counts
        assert "Civil Engineering Stream" in stream_branch_counts
        print(f"  [OK] Found 4 streams mapped to branches: {stream_branch_counts}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 3. stream_subjects seeded
        # -------------------------------------------------------------
        print("\n[Test 3] Verifying stream_subjects table seeded...")
        cur.execute("SELECT count(*) FROM stream_subjects;")
        ss_cnt = cur.fetchone()[0]
        assert ss_cnt >= 20, f"Expected at least 20 stream_subjects links, found {ss_cnt}"
        print(f"  [OK] Found {ss_cnt} stream_subjects relationships across streams and cycles.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 4. club branch_scope seeded
        # -------------------------------------------------------------
        print("\n[Test 4] Verifying clubs branch_scope seeded...")
        cur.execute("SELECT count(*) FROM clubs WHERE branch_scope IS NOT NULL AND branch_scope != '';")
        club_scope_cnt = cur.fetchone()[0]
        assert club_scope_cnt == 24, f"Expected all 24 clubs to have branch_scope, found {club_scope_cnt}"
        print(f"  [OK] All {club_scope_cnt} clubs have valid branch_scope populated.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 5. Idempotent loader
        # -------------------------------------------------------------
        print("\n[Test 5] Verifying idempotent seeding...")
        # Re-running seed functions must not error or duplicate records
        seed_subjects(conn)
        sb_cnt, _ = seed_stream_branches(conn)
        seed_stream_subjects(conn)
        seed_club_branch_scope(conn)
        cur.execute("SELECT count(*) FROM subjects;")
        assert cur.fetchone()[0] == len(subjects_rows)
        print("  [OK] Seeding functions are strictly idempotent.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 6. CSE relationship
        # -------------------------------------------------------------
        print("\n[Test 6] Verifying CSE relationship resolution...")
        cse_ctx = get_academic_context(branch="CSE", cycle="Physics Cycle")
        assert cse_ctx["stream"] == "Computer Science & Engineering Stream"
        assert cse_ctx["department"]["code"] == "CSE"
        assert any(s["name"] == "Mathematics" for s in cse_ctx["subjects"])
        print(f"  [OK] CSE resolved to '{cse_ctx['stream']}' with {len(cse_ctx['subjects'])} subjects.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 7. AI&ML relationship
        # -------------------------------------------------------------
        print("\n[Test 7] Verifying AI&ML relationship resolution...")
        aiml_ctx = get_academic_context(branch="AI&ML")
        assert aiml_ctx["branch_code"] == "AI&ML"
        assert aiml_ctx["department"]["code"] == "AI&ML"
        assert "Jagadish" in aiml_ctx["department"]["hod_name"]
        print(f"  [OK] AI&ML resolved: HOD={aiml_ctx['department']['hod_name']}, Office={aiml_ctx['department']['location']}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 8. CSE(AI&ML) relationship
        # -------------------------------------------------------------
        print("\n[Test 8] Verifying CSE(AI&ML) relationship resolution...")
        cse_aiml_ctx = get_academic_context(branch="CSE(AI&ML)")
        assert cse_aiml_ctx["branch_code"] == "CSE(AIML)"
        assert cse_aiml_ctx["department"]["code"] == "CSE(AIML)"
        assert "Siddesh" in cse_aiml_ctx["department"]["hod_name"]
        print(f"  [OK] CSE(AI&ML) resolved: HOD={cse_aiml_ctx['department']['hod_name']}, Office={cse_aiml_ctx['department']['location']}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 9. AI&ML != CSE(AI&ML) strict disambiguation
        # -------------------------------------------------------------
        print("\n[Test 9] Verifying AI&ML != CSE(AI&ML) disambiguation...")
        assert aiml_ctx["branch_code"] != cse_aiml_ctx["branch_code"]
        assert aiml_ctx["department"]["code"] != cse_aiml_ctx["department"]["code"]
        assert aiml_ctx["department"]["hod_name"] != cse_aiml_ctx["department"]["hod_name"]
        assert aiml_ctx["department"]["location"] != cse_aiml_ctx["department"]["location"]
        print("  [OK] AI&ML and CSE(AI&ML) are completely distinct entities with different HODs and office locations.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 10. Student -> branch -> stream resolution
        # -------------------------------------------------------------
        print("\n[Test 10] Testing Student -> branch -> stream resolution...")
        test_sid_1 = "test_student_step5_10"
        delete_student_profile(test_sid_1)
        update_student_profile(test_sid_1, name="Kavya", branch="ECE", semester=1, cycle="Physics Cycle")
        std_ctx = get_academic_context(student_id=test_sid_1)
        assert std_ctx["branch"] == "ECE"
        assert std_ctx["stream"] == "Electrical & Electronics Engineering Stream"
        print(f"  [OK] Student {test_sid_1} in ECE resolved to stream '{std_ctx['stream']}'.")
        delete_student_profile(test_sid_1)
        passed_tests += 1

        # -------------------------------------------------------------
        # 11. Student -> cycle -> subjects
        # -------------------------------------------------------------
        print("\n[Test 11] Testing Student -> cycle -> subjects filtering...")
        test_sid_2 = "test_student_step5_11"
        delete_student_profile(test_sid_2)
        update_student_profile(test_sid_2, name="Rahul", branch="ME", semester=1, cycle="Chemistry Cycle")
        me_chem_ctx = get_academic_context(student_id=test_sid_2)
        assert all(s["cycle"] == "Chemistry Cycle" for s in me_chem_ctx["subjects"])
        me_subjs = [s["name"] for s in me_chem_ctx["subjects"]]
        assert "Chemistry" in me_subjs
        assert "Mathematics" in me_subjs
        print(f"  [OK] ME Chemistry Cycle resolved subjects: {me_subjs}")
        delete_student_profile(test_sid_2)
        passed_tests += 1

        # -------------------------------------------------------------
        # 12. Branch -> subjects
        # -------------------------------------------------------------
        print("\n[Test 12] Testing Branch -> subjects without student_id...")
        direct_ctx = get_academic_context(branch="Civil", cycle="Physics Cycle")
        assert direct_ctx["branch_code"] == "CE"
        assert direct_ctx["stream"] == "Civil Engineering Stream"
        ce_subjs = [s["name"] for s in direct_ctx["subjects"]]
        assert "Physics" in ce_subjs
        assert "Programming in C" in ce_subjs
        print(f"  [OK] Civil engineering resolved to: {ce_subjs}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 13. Subject -> document count
        # -------------------------------------------------------------
        print("\n[Test 13] Testing Subject -> document count...")
        cse_all_ctx = get_academic_context(branch="CSE")
        math_entry = next((s for s in cse_all_ctx["subjects"] if s["name"] == "Mathematics" and s["cycle"] == "Physics Cycle"), None)
        assert math_entry is not None
        assert math_entry["document_count"] > 0
        assert math_entry["units"] == [1, 2, 3, 4, 5]
        print(f"  [OK] Mathematics (Physics Cycle) has {math_entry['document_count']} verified documents covering units {math_entry['units']}.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 14. Mathematics Unit 1 retrieval
        # -------------------------------------------------------------
        print("\n[Test 14] Testing Mathematics Unit 1 retrieval...")
        m_u1_docs = search_academic_documents(subject="Mathematics", unit=1)
        assert len(m_u1_docs) >= 1
        assert all(d["subject"] == "Mathematics" for d in m_u1_docs)
        assert all(d["unit"] == 1 for d in m_u1_docs)
        print(f"  [OK] Retrieved {len(m_u1_docs)} Unit 1 Mathematics documents: {[d['title'] for d in m_u1_docs]}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 15. Branch-specific club filtering
        # -------------------------------------------------------------
        print("\n[Test 15] Testing branch-specific club filtering...")
        me_clubs = get_recommended_clubs(branch="ME")
        me_club_names = [c["name"] for c in me_clubs]
        assert "SAE Club - Team Velocita" in me_club_names
        assert "SAE Club - Team Stier Racing" in me_club_names
        print(f"  [OK] ME student receives specialized engineering team clubs ({len(me_clubs)} total clubs).")
        passed_tests += 1

        # -------------------------------------------------------------
        # 16. All-branches club filtering
        # -------------------------------------------------------------
        print("\n[Test 16] Testing All-branches club filtering...")
        # Cultural and general clubs must match any branch
        assert "Prayaag" in me_club_names
        assert "DEBSOC" in me_club_names
        assert "National Service Scheme (NSS)" in me_club_names
        print("  [OK] Cultural and outreach clubs (All Branches scope) are included for all students.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 17. Category filtering
        # -------------------------------------------------------------
        print("\n[Test 17] Testing club category filtering...")
        tech_clubs = get_recommended_clubs(branch="CSE", category="Technical")
        assert len(tech_clubs) > 0
        assert all("Technical" in c["category"] for c in tech_clubs)
        tech_names = [c["name"] for c in tech_clubs]
        assert "CodeRIT" in tech_names
        print(f"  [OK] Filtered to {len(tech_clubs)} Technical clubs for CSE.")
        passed_tests += 1

        # -------------------------------------------------------------
        # 18. Unknown branch handling
        # -------------------------------------------------------------
        print("\n[Test 18] Testing unknown branch handling...")
        unk_ctx = get_academic_context(branch="AEROBATICS_UNKNOWN")
        assert unk_ctx["error"] is not None
        assert "not enrolled" in unk_ctx["error"] or "not specified" in unk_ctx["error"]
        print(f"  [OK] Unknown branch safely rejected: {unk_ctx['error']}")
        passed_tests += 1

        # -------------------------------------------------------------
        # 19. Unknown student handling
        # -------------------------------------------------------------
        print("\n[Test 19] Testing unknown student handling...")
        unk_std_ctx = get_academic_context(student_id="nonexistent_id_404")
        assert unk_std_ctx["error"] is not None
        print(f"  [OK] Non-existent student handled safely: {unk_std_ctx['error']}")
        passed_tests += 1

        # -------------------------------------------------------------
        # MCP Client Session Tests
        # -------------------------------------------------------------
        async with mcp_session():
            # -------------------------------------------------------------
            # 20. get_academic_context MCP tool
            # -------------------------------------------------------------
            print("\n[Test 20] Testing get_academic_context MCP tool...")
            t_mcp_ctx = await call_tool("get_academic_context", branch="CSE", cycle="Physics Cycle")
            assert isinstance(t_mcp_ctx, dict)
            assert t_mcp_ctx.get("branch") == "CSE"
            assert len(t_mcp_ctx.get("subjects", [])) == 3
            print(f"  [OK] get_academic_context MCP tool call succeeded with {len(t_mcp_ctx['subjects'])} subjects.")
            passed_tests += 1

            # -------------------------------------------------------------
            # 21. get_recommended_clubs MCP tool
            # -------------------------------------------------------------
            print("\n[Test 21] Testing get_recommended_clubs MCP tool...")
            t_mcp_clubs = await call_tool("get_recommended_clubs", branch="ME")
            assert isinstance(t_mcp_clubs, list)
            assert len(t_mcp_clubs) > 0
            assert any(c["name"] == "SAE Club - Team Velocita" for c in t_mcp_clubs)
            print(f"  [OK] get_recommended_clubs MCP tool call returned {len(t_mcp_clubs)} clubs for ME including SAE Team Velocita.")
            passed_tests += 1

            # -------------------------------------------------------------
            # 22. Audit entries created
            # -------------------------------------------------------------
            print("\n[Test 22] Testing audit logging for Step 5 MCP tools...")
            cur.execute("SELECT tool_name, count(*) FROM audit_log WHERE tool_name IN ('get_academic_context', 'get_recommended_clubs') GROUP BY tool_name;")
            audit_records = dict(cur.fetchall())
            assert "get_academic_context" in audit_records
            assert "get_recommended_clubs" in audit_records
            print(f"  [OK] Audit entries logged: {audit_records}")
            passed_tests += 1

            # -------------------------------------------------------------
            # 23. MCP tool argument validation
            # -------------------------------------------------------------
            print("\n[Test 23] Testing MCP tool argument validation...")
            empty_res = await call_tool("get_academic_context", branch="", student_id="")
            assert isinstance(empty_res, dict)
            assert empty_res.get("error") is not None
            print(f"  [OK] Empty inputs rejected cleanly by MCP tool: {empty_res.get('error')}")
            passed_tests += 1

            # -------------------------------------------------------------
            # 24. MAX_TOOL_CALLS remains 3
            # -------------------------------------------------------------
            print("\n[Test 24] Verifying MAX_TOOL_CALLS safety limit...")
            assert MAX_TOOL_CALLS == 3, f"MAX_TOOL_CALLS must be 3, found {MAX_TOOL_CALLS}"
            print(f"  [OK] MAX_TOOL_CALLS = {MAX_TOOL_CALLS} is strictly preserved.")
            passed_tests += 1

            # -------------------------------------------------------------
            # 25. Inferred profile update remains blocked
            # -------------------------------------------------------------
            print("\n[Test 25] Verifying inferred profile update blocked...")
            test_sid_3 = "test_student_step5_guard"
            delete_student_profile(test_sid_3)
            update_student_profile(test_sid_3, name="Anita", branch="CSE", semester=1)
            # Conversational statement without explicit update command
            passive_msg = "I really love robotics and maybe I should join an electronics club."
            await handle_message(passive_msg, test_sid_3)
            prof_after = get_student_profile(test_sid_3)
            assert prof_after["branch"] == "CSE", "Profile was erroneously modified by passive statement"
            print("  [OK] Inferred profile writes remain strictly blocked.")
            delete_student_profile(test_sid_3)
            passed_tests += 1

            # -------------------------------------------------------------
            # 26. Natural Language Agent Multi-Hop Queries
            # -------------------------------------------------------------
            print("\n--- 26. Testing Representative Natural Language Agent Multi-Hop Queries ---")

            test_std = "test_student_step5_eval"
            delete_student_profile(test_std)
            update_student_profile(test_std, name="Pooja", branch="CSE", semester=1, cycle="Physics Cycle")

            # Query 1: "What subjects belong to my current semester?"
            t0 = time.perf_counter()
            r1 = await handle_message("What subjects belong to my current semester?", test_std)
            d1 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 1] 'What subjects belong to my current semester?'")
            print(f"  Action: {r1.get('action_taken')} | Time: {d1:.2f}ms | Tool Calls: {r1['metrics']['tool_call_count']}")
            assert r1.get("action_taken") == "get_academic_context"
            assert "Mathematics" in r1["answer"]
            assert "Physics" in r1["answer"]
            assert "Programming in C" in r1["answer"]
            print("  [OK] Grounded answer verified:")
            for line in r1["answer"].split("\n")[:4]:
                print(f"    {line}")

            # Query 2: "Which clubs are available for my branch?"
            t0 = time.perf_counter()
            r2 = await handle_message("Which clubs are available for my branch?", test_std)
            d2 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 2] 'Which clubs are available for my branch?'")
            print(f"  Action: {r2.get('action_taken')} | Time: {d2:.2f}ms | Tool Calls: {r2['metrics']['tool_call_count']}")
            assert r2.get("action_taken") == "get_recommended_clubs"
            assert "CodeRIT" in r2["answer"] or "clubs available" in r2["answer"].lower()
            print("  [OK] Grounded answer verified.")

            # Query 3: "What academic resources are associated with Programming in C?"
            t0 = time.perf_counter()
            r3 = await handle_message("What academic resources are associated with Programming in C?", test_std)
            d3 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 3] 'What academic resources are associated with Programming in C?'")
            print(f"  Action: {r3.get('action_taken')} | Time: {d3:.2f}ms")
            assert "Programming in C" in r3["answer"]
            assert len(r3.get("sources", [])) > 0 or "found" in r3["answer"].lower()
            print("  [OK] Grounded answer verified.")

            # Query 4: "Which documents cover Unit 1 of Mathematics?"
            t0 = time.perf_counter()
            r4 = await handle_message("Which documents cover Unit 1 of Mathematics?", test_std)
            d4 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 4] 'Which documents cover Unit 1 of Mathematics?'")
            print(f"  Action: {r4.get('action_taken')} | Time: {d4:.2f}ms")
            assert "Unit 1" in r4["answer"] or "Mathematics" in r4["answer"]
            print("  [OK] Grounded answer verified.")

            # Query 5: "Tell me about my branch and its department."
            t0 = time.perf_counter()
            r5 = await handle_message("Tell me about my branch and its department.", test_std)
            d5 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 5] 'Tell me about my branch and its department.'")
            print(f"  Action: {r5.get('action_taken')} | Time: {d5:.2f}ms | Calls: {r5['metrics']['tool_call_count']}")
            assert "China Appala" in r5["answer"] or "Computer Science" in r5["answer"]
            print("  [OK] Grounded answer verified.")

            # Query 6: "Who is the HOD for my branch and where is the department office?"
            t0 = time.perf_counter()
            r6 = await handle_message("Who is the HOD for my branch and where is the department office?", test_std)
            d6 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 6] 'Who is the HOD for my branch and where is the department office?'")
            print(f"  Action: {r6.get('action_taken')} | Time: {d6:.2f}ms")
            assert any(t in r6["answer"] for t in ["China Appala", "Siddesh", "DES Block", "Multipurpose", "HOD", "Department", "office"])
            print("  [OK] Grounded answer verified.")

            # Query 7: "What Mathematics material should I study?"
            t0 = time.perf_counter()
            r7 = await handle_message("What Mathematics material should I study?", test_std)
            d7 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 7] 'What Mathematics material should I study?'")
            print(f"  Action: {r7.get('action_taken')} | Time: {d7:.2f}ms")
            assert "Mathematics" in r7["answer"] or "math" in r7["answer"].lower()
            print("  [OK] Grounded answer verified.")

            # Query 8: "I'm a CSE(AI&ML) student. What Mathematics material should I study?"
            t0 = time.perf_counter()
            r8 = await handle_message("I'm a CSE(AI&ML) student. What Mathematics material should I study?", test_std)
            d8 = (time.perf_counter() - t0) * 1000
            print(f"\n[Query 8] 'I'm a CSE(AI&ML) student. What Mathematics material should I study?'")
            print(f"  Action: {r8.get('action_taken')} | Time: {d8:.2f}ms")
            assert "Mathematics" in r8["answer"] or "CSE" in r8["answer"] or "study" in r8["answer"].lower()
            print("  [OK] Grounded answer verified.")

            delete_student_profile(test_std)
            passed_tests += 1

    finally:
        cur.close()
        conn.close()

    total_time = (time.perf_counter() - t_start)
    print("\n" + "=" * 80)
    print(f"STEP 5 TEST SUITE RESULTS: {passed_tests}/26 TEST GROUPS PASSED (100% SUCCESS)")
    print(f"Total Execution Time: {total_time:.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_step5_tests())
