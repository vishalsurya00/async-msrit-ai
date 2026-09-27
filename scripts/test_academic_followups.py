"""
RIT NEXUS — Academic Resource Links & Follow-up Resolution Tests
Verifies:
1. Physics Unit 1 ambiguous selection
2. "Lasers" resolves to Physics Unit 1 Lasers
3. "laser unit 1" resolves correctly
4. "the first one" resolves when deterministic
5. Ambiguous selection asks clarification without discarding context
6. Physics question-paper list followed by "2023 May question paper"
7. Physics context is preserved without re-asking subject
8. Programming in C followed by "Cprog"
9. No local filesystem path appears in user-facing output (data/raw, etc.)
10. Public resource URL (https://ritnotebook.pages.dev/notes/first) appears
11. Unknown follow-up does not corrupt context
12. Unrelated query clears/does not incorrectly use academic pending state
13. Qwen is NOT called for deterministic follow-up resolution
14. FLOW A, FLOW B, FLOW C, FLOW D exact flows
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.agent import handle_message
from backend.conversation_context import (
    clear_academic_context,
    get_academic_context,
    PUBLIC_FIRST_YEAR_URL,
)


def assert_no_internal_paths(text: str):
    """Assert that no internal filesystem paths or raw data directories are in the text."""
    forbidden = ["data/raw", "data\\raw", "local_file_path", ".pdf", "__14ZLhu4G", "first_year/by_folder"]
    for f in forbidden:
        assert f not in text, f"Internal path leak detected ('{f}') in response: {text}"


async def test_suite():
    print("=" * 70)
    print("RUNNING ACADEMIC RESOURCE LINKS & FOLLOW-UP RESOLUTION TEST SUITE")
    print("=" * 70)

    # ----------------------------------------------------
    # TEST 1 & 2 & 3: Physics Unit 1 and resolutions
    # ----------------------------------------------------
    print("\n--- Test 1, 2, 3: Physics Unit 1 Ambiguous & Specific Follow-ups ---")
    sid = "test_user_phy"
    clear_academic_context(sid)

    # Turn 1: ambiguous request
    r1 = await handle_message("Give me the Physics Unit 1 notes.", sid)
    assert "Unit 1 (Lasers)" in r1["answer"], f"Expected Lasers in candidate list, got: {r1['answer']}"
    assert "Unit 1 (Optical Fibres)" in r1["answer"], f"Expected Optical Fibres in candidate list, got: {r1['answer']}"
    assert PUBLIC_FIRST_YEAR_URL in r1["answer"]
    assert_no_internal_paths(r1["answer"])

    ctx = get_academic_context(sid)
    assert ctx is not None
    assert ctx["subject"].lower() == "physics"
    assert ctx["awaiting_selection"] is True
    assert len(ctx["candidates"]) == 2
    print("[PASS] Test 1: Physics Unit 1 lists candidates and sets pending state")

    # Turn 2: "Lasers" with spy on Qwen to ensure deterministic bypass
    with patch("backend.rag.answer_question") as mock_qwen_rag, \
         patch("backend.agentic.run_agentic_workflow") as mock_qwen_agentic:
        r2 = await handle_message("Lasers", sid)
        assert mock_qwen_rag.call_count == 0, "Qwen RAG was invoked for deterministic follow-up!"
        assert mock_qwen_agentic.call_count == 0, "Qwen Agentic workflow was invoked for deterministic follow-up!"

    assert "Unit 1 (Lasers)" in r2["answer"] or "Lasers" in r2["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r2["answer"]
    assert_no_internal_paths(r2["answer"])
    assert r2["action_taken"] == "academic_followup_resolution"
    print("[PASS] Test 2: 'Lasers' resolves to Physics Unit 1 Lasers without calling Qwen")

    # Test 3: "laser unit 1" resolution
    clear_academic_context(sid)
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    with patch("backend.rag.answer_question") as mock_qwen_rag, \
         patch("backend.agentic.run_agentic_workflow") as mock_qwen_agentic:
        r3 = await handle_message("laser unit 1", sid)
        assert mock_qwen_rag.call_count == 0
        assert mock_qwen_agentic.call_count == 0

    assert "Lasers" in r3["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r3["answer"]
    assert_no_internal_paths(r3["answer"])
    assert r3["action_taken"] == "academic_followup_resolution"
    print("[PASS] Test 3: 'laser unit 1' resolves correctly")

    # ----------------------------------------------------
    # TEST 4: Ordinal resolution ("the first one")
    # ----------------------------------------------------
    print("\n--- Test 4: Ordinal Resolution ('the first one') ---")
    clear_academic_context(sid)
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    with patch("backend.rag.answer_question") as mock_qwen_rag, \
         patch("backend.agentic.run_agentic_workflow") as mock_qwen_agentic:
        r4 = await handle_message("the first one", sid)
        assert mock_qwen_rag.call_count == 0
        assert mock_qwen_agentic.call_count == 0

    assert "Unit 1 (Lasers)" in r4["answer"] or "Lasers" in r4["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r4["answer"]
    assert_no_internal_paths(r4["answer"])
    assert r4["action_taken"] == "academic_followup_resolution"
    print("[PASS] Test 4: 'the first one' resolves to first candidate")

    # ----------------------------------------------------
    # TEST 5: Ambiguous follow-up asks clarification without discarding context
    # ----------------------------------------------------
    print("\n--- Test 5: Ambiguous Follow-up Asks Clarification & Preserves Context ---")
    clear_academic_context(sid)
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    r5 = await handle_message("Unit 1", sid)
    assert "Which Physics Unit 1 notes do you want: Lasers or Optical Fibres?" in r5["answer"]
    assert r5["action_taken"] == "academic_followup_clarification"
    # Verify context is preserved
    ctx_after = get_academic_context(sid)
    assert ctx_after is not None, "Context should be preserved on clarification"
    assert ctx_after["awaiting_selection"] is True

    # User now clarifies "Optical Fibres"
    r5_res = await handle_message("Optical Fibres", sid)
    assert "Optical Fibres" in r5_res["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r5_res["answer"]
    assert_no_internal_paths(r5_res["answer"])
    print("[PASS] Test 5: Ambiguous selection clarification works and subsequent resolution succeeds")

    # ----------------------------------------------------
    # TEST 6 & 7: Physics Question Papers
    # ----------------------------------------------------
    print("\n--- Test 6 & 7: Physics Question Papers & Context Preservation ---")
    sid_pyq = "test_user_pyq"
    clear_academic_context(sid_pyq)
    r6 = await handle_message("Do you have question papers for Physics?", sid_pyq)
    assert "2023 May" in r6["answer"]
    assert "2023 September" in r6["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r6["answer"]
    assert_no_internal_paths(r6["answer"])

    with patch("backend.rag.answer_question") as mock_qwen_rag, \
         patch("backend.agentic.run_agentic_workflow") as mock_qwen_agentic:
        r7 = await handle_message("2023 May question paper", sid_pyq)
        assert mock_qwen_rag.call_count == 0
        assert mock_qwen_agentic.call_count == 0

    assert "Physics 2023 May question paper" in r7["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r7["answer"]
    assert_no_internal_paths(r7["answer"])
    assert r7["action_taken"] == "academic_followup_resolution"
    print("[PASS] Test 6 & 7: Physics question papers and context preservation verified")

    # ----------------------------------------------------
    # TEST 8: Programming in C followed by "Cprog"
    # ----------------------------------------------------
    print("\n--- Test 8: Programming in C followed by 'Cprog' ---")
    sid_c = "test_user_c"
    clear_academic_context(sid_c)
    r8_1 = await handle_message("Find Programming in C notes.", sid_c)
    assert "Cprog" in r8_1["answer"]
    assert "C prog ch 1,2,3" in r8_1["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r8_1["answer"]
    assert_no_internal_paths(r8_1["answer"])

    with patch("backend.rag.answer_question") as mock_qwen_rag, \
         patch("backend.agentic.run_agentic_workflow") as mock_qwen_agentic:
        r8_2 = await handle_message("Cprog", sid_c)
        assert mock_qwen_rag.call_count == 0
        assert mock_qwen_agentic.call_count == 0

    assert "Cprog" in r8_2["answer"]
    assert PUBLIC_FIRST_YEAR_URL in r8_2["answer"]
    assert_no_internal_paths(r8_2["answer"])
    assert r8_2["action_taken"] == "academic_followup_resolution"
    print("[PASS] Test 8: 'Cprog' resolves directly without routing to unknown clarification")

    # ----------------------------------------------------
    # TEST 11: Unknown follow-up does not corrupt context
    # ----------------------------------------------------
    print("\n--- Test 11: Unknown Follow-up Does Not Corrupt Context ---")
    clear_academic_context(sid)
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    # A message that doesn't match any candidate and isn't another recognized intent
    r11 = await handle_message("asdfghjk", sid)
    ctx11 = get_academic_context(sid)
    assert ctx11 is not None, "Context should remain intact"
    assert ctx11["subject"].lower() == "physics"
    print("[PASS] Test 11: Unknown follow-up preserves context safely")

    # ----------------------------------------------------
    # TEST 12: Unrelated query clears/does not use academic pending state
    # ----------------------------------------------------
    print("\n--- Test 12: Unrelated Query Clears Context & Routes Correctly ---")
    clear_academic_context(sid)
    await handle_message("Give me the Physics Unit 1 notes.", sid)

    # Greeting should clear context
    r12_greet = await handle_message("Hello there", sid)
    assert r12_greet["action_taken"] == "conversation"
    assert get_academic_context(sid) is None
    print("[PASS] Test 12a: Greeting correctly bypassed and cleared context")

    # Identity should clear context
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    r12_id = await handle_message("Who are you?", sid)
    assert r12_id["action_taken"] == "conversation"
    assert get_academic_context(sid) is None
    print("[PASS] Test 12b: Identity query correctly bypassed and cleared context")

    # Department query should clear context
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    r12_dept = await handle_message("Who is the HOD of CSE?", sid)
    assert "Dr. R. China Appala Naidu" in r12_dept["answer"] or "Head of Department" in r12_dept["answer"] or "HOD" in r12_dept["answer"]
    assert get_academic_context(sid) is None
    print("[PASS] Test 12c: Department query correctly bypassed and cleared context")

    # Club query should clear context
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    r12_club = await handle_message("Tell me about SecuRIT", sid)
    assert "SecuRIT" in r12_club["answer"]
    assert get_academic_context(sid) is None
    print("[PASS] Test 12d: Club query correctly bypassed and cleared context")

    # Explicit profile update should clear context
    await handle_message("Give me the Physics Unit 1 notes.", sid)
    r12_prof = await handle_message("My branch is AIML", sid)
    assert "AI&ML" in r12_prof["answer"] or "AIML" in r12_prof["answer"]
    assert get_academic_context(sid) is None
    print("[PASS] Test 12e: Profile update correctly bypassed and cleared context")

    # ----------------------------------------------------
    # EXACT FLOW TESTS A, B, C, D
    # ----------------------------------------------------
    print("\n--- EXACT FLOWS: A, B, C, D ---")

    # FLOW A
    print("Testing FLOW A...")
    clear_academic_context("flow_a_user")
    fa_1 = await handle_message("Give me the Physics Unit 1 notes.", "flow_a_user")
    assert "Lasers" in fa_1["answer"] and "Optical Fibres" in fa_1["answer"]
    fa_2 = await handle_message("laser unit 1", "flow_a_user")
    assert "Lasers" in fa_2["answer"]
    assert PUBLIC_FIRST_YEAR_URL in fa_2["answer"]
    assert_no_internal_paths(fa_2["answer"])
    print("[PASS] FLOW A verified")

    # FLOW B
    print("Testing FLOW B...")
    clear_academic_context("flow_b_user")
    fb_1 = await handle_message("Do you have question papers for Physics?", "flow_b_user")
    assert "2023 May" in fb_1["answer"]
    fb_2 = await handle_message("2023 May question ppr", "flow_b_user")
    assert "Physics 2023 May question paper" in fb_2["answer"]
    assert PUBLIC_FIRST_YEAR_URL in fb_2["answer"]
    assert_no_internal_paths(fb_2["answer"])
    print("[PASS] FLOW B verified")

    # FLOW C
    print("Testing FLOW C...")
    clear_academic_context("flow_c_user")
    fc_1 = await handle_message("Find Programming in C notes.", "flow_c_user")
    assert "Cprog" in fc_1["answer"]
    fc_2 = await handle_message("Cprog", "flow_c_user")
    assert "Cprog" in fc_2["answer"]
    assert PUBLIC_FIRST_YEAR_URL in fc_2["answer"]
    assert_no_internal_paths(fc_2["answer"])
    print("[PASS] FLOW C verified")

    # FLOW D
    print("Testing FLOW D...")
    clear_academic_context("flow_d_user")
    fd_1 = await handle_message("Which documents cover Unit 1 of Mathematics?", "flow_d_user")
    assert "Differential Calculus" in fd_1["answer"]
    fd_2 = await handle_message("Unit 1 Differential Calculus - II", "flow_d_user")
    assert "Differential Calculus" in fd_2["answer"]
    assert PUBLIC_FIRST_YEAR_URL in fd_2["answer"]
    assert_no_internal_paths(fd_2["answer"])
    print("[PASS] FLOW D verified")

    print("\n" + "=" * 70)
    print("ALL ACADEMIC FOLLOW-UP & RESOURCE LINK TESTS PASSED (100%)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_suite())
