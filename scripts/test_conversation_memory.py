"""
Comprehensive verification test suite for Phase 2:
Multi-turn conversation memory, context resolution, language control, and path privacy.
"""
import sys
import os
import asyncio
import uuid
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.conversation_store import (
    create_session,
    session_exists,
    get_or_create_session,
    add_message,
    get_recent_messages,
    delete_session
)
from backend.conversation_context import (
    resolve_conversation_context,
    update_session_context_from_interaction,
    resolve_academic_followup,
    clear_academic_context,
    PUBLIC_FIRST_YEAR_URL
)
from backend.language_control import contains_cjk, safe_qwen_generate
from backend.agent import handle_message
from backend.main import ask_endpoint, AskRequest


TEST_STUDENT_ID = "1MS24CS999"


def test_section(title: str):
    print(f"\n{'='*70}\n{title}\n{'='*70}")


async def run_all_tests():
    passed = 0
    failed = 0

    def record_pass(desc: str):
        nonlocal passed
        passed += 1
        print(f"  [PASS] {desc}")

    def record_fail(desc: str, err: Exception):
        nonlocal failed
        failed += 1
        print(f"  [FAIL] {desc}: {err}")

    # =========================================================================
    # PART 1: Conversation Store Layer (PostgreSQL)
    # =========================================================================
    test_section("PART 1: Conversation Store Layer (PostgreSQL)")

    test_sid = None
    try:
        # 1. Create session
        test_sid = create_session(student_id=TEST_STUDENT_ID)
        assert session_exists(test_sid), "Session was not found in conversation_sessions"
        uuid_obj = uuid.UUID(test_sid)
        assert str(uuid_obj) == test_sid, "Session ID is not a valid UUID"
        record_pass("create_session() generates valid UUID and persists in PostgreSQL")
    except Exception as e:
        record_fail("create_session()", e)

    try:
        # 2. get_or_create_session existing
        sid_retrieved, is_new = get_or_create_session(test_sid, student_id=TEST_STUDENT_ID)
        assert sid_retrieved == test_sid, "Retrieved session ID mismatch"
        assert not is_new, "Expected is_new to be False for existing session"
        record_pass("get_or_create_session() correctly reuses existing session")
    except Exception as e:
        record_fail("get_or_create_session() existing", e)

    try:
        # 3. get_or_create_session new
        fresh_sid, is_new = get_or_create_session(None, student_id=TEST_STUDENT_ID)
        assert session_exists(fresh_sid), "Fresh session was not created in DB"
        assert is_new, "Expected is_new to be True for fresh session"
        delete_session(fresh_sid)
        record_pass("get_or_create_session(None) creates fresh session when None passed")
    except Exception as e:
        record_fail("get_or_create_session() new", e)

    try:
        # 4. add_message user & assistant
        m1 = add_message(test_sid, "user", "Who is the HOD of CSE?", {"student_id": TEST_STUDENT_ID})
        m2 = add_message(test_sid, "assistant", "The HOD of Computer Science and Engineering is Dr. Jagadish S Kallimani.", {"action_taken": "department_lookup"})
        assert m1 > 0 and m2 > m1, "Message IDs were not created sequentially"
        record_pass("add_message() persists user and assistant messages with metadata")
    except Exception as e:
        record_fail("add_message()", e)

    try:
        # 5. get_recent_messages chronological ordering
        recent = get_recent_messages(test_sid, limit=5)
        assert len(recent) == 2, f"Expected 2 messages, got {len(recent)}"
        assert recent[0]["role"] == "user" and recent[0]["content"] == "Who is the HOD of CSE?"
        assert recent[1]["role"] == "assistant"
        record_pass("get_recent_messages() retrieves chronological messages with metadata")
    except Exception as e:
        record_fail("get_recent_messages()", e)

    try:
        # 6. Session isolation
        other_sid = create_session(student_id="1MS24CS888")
        add_message(other_sid, "user", "Message in session B")
        msgs_a = get_recent_messages(test_sid, limit=10)
        msgs_b = get_recent_messages(other_sid, limit=10)
        assert len(msgs_b) == 1, "Session B should have 1 message"
        assert all(m["content"] != "Message in session B" for m in msgs_a), "Session A leaked messages from Session B"
        delete_session(other_sid)
        record_pass("Session isolation: messages in session A and B do not leak across sessions")
    except Exception as e:
        record_fail("Session isolation", e)

    # =========================================================================
    # PART 2: Language Control & CJK Safety
    # =========================================================================
    test_section("PART 2: Language Control & CJK Safety")

    try:
        assert not contains_cjk("This is a normal English sentence about MSRIT engineering notes.")
        assert not contains_cjk("Physics Unit 1 - Lasers & Optical Fibres.")
        assert contains_cjk("这是关于物理学的笔记")  # Chinese
        assert contains_cjk("レーザーに関する説明")  # Japanese
        assert contains_cjk("컴퓨터 공학과")          # Korean
        record_pass("contains_cjk() accurately identifies CJK text and clears English text")
    except Exception as e:
        record_fail("contains_cjk()", e)

    try:
        # Test safe_qwen_generate with English generation
        test_prompt = "What is the capital of France? Answer in one word."
        ans = safe_qwen_generate(test_prompt, deterministic_fallback="Paris", timeout=30)
        assert ans and not contains_cjk(ans), f"Expected clean English output, got: {ans!r}"
        record_pass("safe_qwen_generate() outputs verified English text without CJK corruption")
    except Exception as e:
        record_fail("safe_qwen_generate()", e)

    # =========================================================================
    # PART 3: Document Path Privacy & Public URLs
    # =========================================================================
    test_section("PART 3: Document Path Privacy & Public URLs")

    try:
        res_doc = await handle_message("Give me Physics Unit 2 notes", student_id=TEST_STUDENT_ID)
        ans = res_doc.get("answer", "")
        sources = res_doc.get("sources", [])

        # Check path privacy in answer
        assert "data/raw" not in ans.lower(), f"Internal data/raw path leaked in answer: {ans}"
        assert "local_file_path" not in ans.lower(), "local_file_path leaked in answer"
        assert PUBLIC_FIRST_YEAR_URL in ans, f"Expected public URL in answer: {ans}"

        # Check path privacy in sources
        for s in sources:
            src_str = str(s)
            assert "data/raw" not in src_str.lower(), f"Internal data/raw leaked in source: {s}"
            assert s.get("public_url") == PUBLIC_FIRST_YEAR_URL, f"Expected public_url in source: {s}"

        record_pass("Document path privacy: 0 path leaks, public resource URL provided")
    except Exception as e:
        record_fail("Document path privacy", e)

    # =========================================================================
    # PART 4: Multi-Turn Academic Follow-up (Candidate Selection)
    # =========================================================================
    test_section("PART 4: Multi-Turn Academic Candidate Selection Follow-up")

    sess_acad = create_session(student_id=TEST_STUDENT_ID)
    try:
        # Turn 1: Ambiguous document query offering candidates
        req1 = AskRequest(message="give me physics unit 1 notes", student_id=TEST_STUDENT_ID, session_id=sess_acad)
        r1 = await ask_endpoint(req1)
        ans1 = r1.get("answer", "")
        assert "Lasers" in ans1 and "Optical" in ans1, f"Expected candidate options in answer: {ans1}"
        record_pass("Turn 1: Physics Unit 1 asks candidate clarification (Lasers or Optical Fibres)")

        # Turn 2: Follow-up with keyword "lasers"
        req2 = AskRequest(message="lasers", student_id=TEST_STUDENT_ID, session_id=sess_acad)
        r2 = await ask_endpoint(req2)
        ans2 = r2.get("answer", "")
        assert "Laser" in ans2 or "Unit 1" in ans2, f"Expected resolved laser notes, got: {ans2}"
        assert PUBLIC_FIRST_YEAR_URL in ans2, "Expected public URL in resolved answer"
        assert "data/raw" not in ans2.lower(), "data/raw leaked in resolved answer"
        record_pass("Turn 2: Follow-up 'lasers' resolved unambiguously with public URL")
    except Exception as e:
        record_fail("Academic candidate follow-up Flow A", e)
    finally:
        delete_session(sess_acad)

    sess_ord = create_session(student_id=TEST_STUDENT_ID)
    try:
        # Flow B: Ordinal selection "the first one"
        await ask_endpoint(AskRequest(message="give me physics unit 1 notes", student_id=TEST_STUDENT_ID, session_id=sess_ord))
        r_ord = await ask_endpoint(AskRequest(message="the first one", student_id=TEST_STUDENT_ID, session_id=sess_ord))
        ans_ord = r_ord.get("answer", "")
        assert PUBLIC_FIRST_YEAR_URL in ans_ord, f"Expected resolved note with public URL: {ans_ord}"
        assert "data/raw" not in ans_ord.lower(), "data/raw leaked in ordinal answer"
        record_pass("Flow B: Ordinal follow-up 'the first one' resolved correctly")
    except Exception as e:
        record_fail("Academic candidate follow-up Flow B", e)
    finally:
        delete_session(sess_ord)

    sess_qp = create_session(student_id=TEST_STUDENT_ID)
    try:
        # Flow C: Physics question paper -> "2023 May"
        await ask_endpoint(AskRequest(message="physics question papers", student_id=TEST_STUDENT_ID, session_id=sess_qp))
        r_qp = await ask_endpoint(AskRequest(message="2023 May", student_id=TEST_STUDENT_ID, session_id=sess_qp))
        ans_qp = r_qp.get("answer", "")
        assert "2023 May" in ans_qp and PUBLIC_FIRST_YEAR_URL in ans_qp, f"Expected 2023 May paper: {ans_qp}"
        record_pass("Flow C: Question paper candidate follow-up '2023 May' resolved")
    except Exception as e:
        record_fail("Academic candidate follow-up Flow C", e)
    finally:
        delete_session(sess_qp)

    # =========================================================================
    # PART 5: Multi-Turn Entity & Pronoun Follow-up
    # =========================================================================
    test_section("PART 5: Multi-Turn Entity & Pronoun Follow-up")

    sess_pronoun = create_session(student_id=TEST_STUDENT_ID)
    try:
        # Turn 1: "Who is the HOD of CSE?"
        req1 = AskRequest(message="Who is the HOD of CSE?", student_id=TEST_STUDENT_ID, session_id=sess_pronoun)
        r1 = await ask_endpoint(req1)
        ans1 = r1.get("answer", "")
        assert "Jagadish" in ans1 or "CSE" in ans1 or "Computer Science" in ans1, f"Expected CSE HOD in answer: {ans1}"
        record_pass("Turn 1: 'Who is the HOD of CSE?' answered with CSE HOD details")

        # Turn 2: "Where is his department?"
        req2 = AskRequest(message="Where is his department?", student_id=TEST_STUDENT_ID, session_id=sess_pronoun)
        r2 = await ask_endpoint(req2)
        ans2 = r2.get("answer", "")
        assert ("DES Block" in ans2 or "DES" in ans2) and r2.get("action_taken") in ("department", "department_lookup", "lookup_department", "lookup_branch"), f"Expected DES Block department location: {ans2} (action: {r2.get('action_taken')})"
        record_pass("Turn 2: 'Where is his department?' successfully resolved to CSE location (DES Block) without RAG")

        # Turn 3: "Which block is it in?"
        req3 = AskRequest(message="Which block is it in?", student_id=TEST_STUDENT_ID, session_id=sess_pronoun)
        r3 = await ask_endpoint(req3)
        ans3 = r3.get("answer", "")
        assert ("DES Block" in ans3 or "DES" in ans3), f"Expected DES Block in answer: {ans3}"
        record_pass("Turn 3: 'Which block is it in?' successfully resolved to CSE block (DES Block)")
    except Exception as e:
        record_fail("Entity & Pronoun follow-up", e)
    finally:
        delete_session(sess_pronoun)

    # =========================================================================
    # PART 6: Multi-Turn Explanation Continuation Follow-up
    # =========================================================================
    test_section("PART 6: Multi-Turn Explanation Continuation Follow-up")

    sess_exp = create_session(student_id=TEST_STUDENT_ID)
    try:
        # Turn 1: "Explain corrosion mechanism"
        req1 = AskRequest(message="Explain corrosion mechanism", student_id=TEST_STUDENT_ID, session_id=sess_exp)
        r1 = await ask_endpoint(req1)
        ans1 = r1.get("answer", "")
        assert len(ans1) > 20, "Expected non-empty explanation of corrosion mechanism"
        record_pass("Turn 1: 'Explain corrosion mechanism' answered via academic notes")

        # Turn 2: "What happens at the cathode?"
        req2 = AskRequest(message="What happens at the cathode?", student_id=TEST_STUDENT_ID, session_id=sess_exp)
        r2 = await ask_endpoint(req2)
        ans2 = r2.get("answer", "")
        assert ("cathode" in ans2.lower() or "reduction" in ans2.lower() or "oxygen" in ans2.lower() or "corrosion" in ans2.lower()), f"Expected cathodic reaction explanation: {ans2}"
        record_pass("Turn 2: 'What happens at the cathode?' successfully contextualized with corrosion mechanism")
    except Exception as e:
        record_fail("Explanation follow-up", e)
    finally:
        delete_session(sess_exp)

    # =========================================================================
    # PART 7: Stale Context Protection
    # =========================================================================
    test_section("PART 7: Stale Context Protection")

    sess_stale = create_session(student_id=TEST_STUDENT_ID)
    try:
        # User triggers candidate selection
        await ask_endpoint(AskRequest(message="give me physics unit 1 notes", student_id=TEST_STUDENT_ID, session_id=sess_stale))
        # User suddenly asks a greeting
        r_greet = await ask_endpoint(AskRequest(message="Hello, how are you?", student_id=TEST_STUDENT_ID, session_id=sess_stale))
        ans_greet = r_greet.get("answer", "")
        assert "Which Physics Unit 1" not in ans_greet and ("hello" in ans_greet.lower() or "hi" in ans_greet.lower() or "help" in ans_greet.lower()), f"Greeting was hijacked by stale academic context: {ans_greet}"
        record_pass("Stale-context guard: greeting safely clears pending academic context")

        # User suddenly asks an identity query
        r_ident = await ask_endpoint(AskRequest(message="Who are you?", student_id=TEST_STUDENT_ID, session_id=sess_stale))
        ans_ident = r_ident.get("answer", "")
        assert "MSRIT AI" in ans_ident, f"Identity query was hijacked: {ans_ident}"
        record_pass("Stale-context guard: identity query safely handled without context bleed")
    except Exception as e:
        record_fail("Stale context protection", e)
    finally:
        delete_session(sess_stale)

    # =========================================================================
    # PART 8: End-to-End POST /ask Contract & Persistence
    # =========================================================================
    test_section("PART 8: End-to-End POST /ask Contract & Persistence")

    try:
        # Request with no session_id should return a session_id
        res_fresh = await ask_endpoint(AskRequest(message="Who is the HOD of Mechanical?", student_id=TEST_STUDENT_ID))
        new_sid = res_fresh.get("session_id")
        assert new_sid and session_exists(new_sid), f"No valid session_id returned: {res_fresh}"
        record_pass("POST /ask automatically creates and returns session_id when none provided")

        # Second request using that session_id
        res_follow = await ask_endpoint(AskRequest(message="Where is his office?", student_id=TEST_STUDENT_ID, session_id=new_sid))
        assert res_follow.get("session_id") == new_sid, "session_id was not preserved in response"
        ans_follow = res_follow.get("answer", "")
        assert "Mechanical" in ans_follow or "ME" in ans_follow or "ESB" in ans_follow or "Apex" in ans_follow or "LHC" in ans_follow, f"Pronoun resolution across /ask failed: {ans_follow}"
        record_pass("POST /ask preserves session_id and resolves pronouns across separate calls")

        # Verify DB records
        history_msgs = get_recent_messages(new_sid, limit=10)
        assert len(history_msgs) == 4, f"Expected 4 messages (2 user, 2 assistant), got {len(history_msgs)}"
        assert history_msgs[0]["role"] == "user"
        assert history_msgs[1]["role"] == "assistant"
        assert history_msgs[2]["role"] == "user"
        assert history_msgs[3]["role"] == "assistant"
        record_pass("Database verification: All turns correctly persisted to conversation_messages in PostgreSQL")
        delete_session(new_sid)
    except Exception as e:
        record_fail("End-to-End POST /ask", e)

    # =========================================================================
    # SUMMARY
    # =========================================================================
    test_section("PHASE 2 TEST SUMMARY")
    total = passed + failed
    print(f"Total Tests Executed: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    if failed == 0:
        print("ALL PHASE 2 VERIFICATION TESTS PASSED SUCCESSFULLY! [OK]")
    else:
        print(f"WARNING: {failed} test(s) failed.")

    if test_sid:
        delete_session(test_sid)

    try:
        from backend.mcp_client import get_mcp_client
        client = get_mcp_client()
        if client:
            await client.close()
    except Exception:
        pass

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
