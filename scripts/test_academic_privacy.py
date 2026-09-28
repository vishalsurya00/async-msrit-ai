"""
Privacy & Document Path Safety Regression Test Suite.
Verifies that:
1. Strings containing:
   - data/raw/
   - data\\raw
   - local_file_path
   - folder IDs (e.g., __10neY4vT, __14ZLhu4G, drive folder links)
   NEVER appear in any final user-facing academic responses or source cards.
2. The 5 exact flows required:
   - "Give me the Mathematics notes"
   - "Give me Unit 1 Mathematics notes"
   - "Give me the Physics question papers"
   - "Give me Physics Unit 1 Lasers notes"
   - "Give me the 2023 May Physics question paper"
3. Multi-turn follow-up and ordinal selection safety.
4. HTTP POST /ask contract safety.
"""
import asyncio
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.agent import handle_message
from backend.main import ask_endpoint, AskRequest
from backend.conversation_store import create_session, delete_session
from backend.conversation_context import PUBLIC_FIRST_YEAR_URL

FORBIDDEN_PATTERNS = [
    r'data[/\\]raw',
    r'local_file_path',
    r'__[0-9a-zA-Z_-]{8,}',
    r'by_folder',
    r'drive\.google\.com/drive/folders',
    r'(?<!https)(?<!http)(?:\b|^)[A-Za-z]:[/\\]',
    r'\.pdf\b'
]


def assert_safe(text: str, context_label: str):
    """Assert that a string contains no forbidden internal filesystem paths or IDs."""
    lower = text.lower()
    for pat in FORBIDDEN_PATTERNS:
        assert not re.search(pat, lower, re.I), (
            f"LEAK DETECTED ({pat}) in {context_label}:\n{text}"
        )


def assert_sources_safe(sources: list, context_label: str):
    """Assert that every source dict contains only safe, public metadata."""
    for s in sources:
        assert isinstance(s, dict), f"Expected dict source in {context_label}"
        # Disallowed keys
        assert "local_file_path" not in s, f"'local_file_path' key leaked in source: {s}"
        
        # Check all string values
        for k, v in s.items():
            if isinstance(v, str):
                assert_safe(v, f"{context_label} source[{k}]")
        
        # Check URLs
        url = s.get("public_url") or s.get("source_url") or s.get("file_path")
        assert url == PUBLIC_FIRST_YEAR_URL, (
            f"Expected public resource URL ({PUBLIC_FIRST_YEAR_URL}), got: {url}"
        )


async def main():
    print("=" * 70)
    print("RUNNING PRIVACY & DOCUMENT PATH SAFETY REGRESSION TESTS")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # PART 1: The 5 Exact Required Academic Flows
    # -------------------------------------------------------------------------
    print("\n--- PART 1: Testing the 5 Exact Academic Flows ---")
    
    # Flow 1: "Give me the Mathematics notes"
    print("\n[Flow 1] 'Give me the Mathematics notes'")
    res1 = await handle_message("Give me the Mathematics notes", student_id="test_priv_1")
    ans1 = res1.get("answer", "")
    src1 = res1.get("sources", [])
    assert "Mathematics" in ans1
    assert PUBLIC_FIRST_YEAR_URL in ans1
    assert len(src1) >= 1
    assert_safe(ans1, "Flow 1 answer")
    assert_sources_safe(src1, "Flow 1 sources")
    print("  -> Passed. 0 leaks, public URL verified.")

    # Flow 2: "Give me Unit 1 Mathematics notes"
    print("\n[Flow 2] 'Give me Unit 1 Mathematics notes'")
    res2 = await handle_message("Give me Unit 1 Mathematics notes", student_id="test_priv_2")
    ans2 = res2.get("answer", "")
    src2 = res2.get("sources", [])
    assert "Mathematics" in ans2 and "Unit 1" in ans2
    assert PUBLIC_FIRST_YEAR_URL in ans2
    assert len(src2) >= 1
    assert_safe(ans2, "Flow 2 answer")
    assert_sources_safe(src2, "Flow 2 sources")
    print("  -> Passed. 0 leaks, public URL verified.")

    # Flow 3: "Give me the Physics question papers"
    print("\n[Flow 3] 'Give me the Physics question papers'")
    res3 = await handle_message("Give me the Physics question papers", student_id="test_priv_3")
    ans3 = res3.get("answer", "")
    src3 = res3.get("sources", [])
    assert "Physics" in ans3
    assert PUBLIC_FIRST_YEAR_URL in ans3
    assert len(src3) >= 1
    assert_safe(ans3, "Flow 3 answer")
    assert_sources_safe(src3, "Flow 3 sources")
    print("  -> Passed. 0 leaks, public URL verified.")

    # Flow 4: "Give me Physics Unit 1 Lasers notes"
    print("\n[Flow 4] 'Give me Physics Unit 1 Lasers notes'")
    res4 = await handle_message("Give me Physics Unit 1 Lasers notes", student_id="test_priv_4")
    ans4 = res4.get("answer", "")
    src4 = res4.get("sources", [])
    assert "Physics" in ans4 and "Lasers" in ans4
    assert PUBLIC_FIRST_YEAR_URL in ans4
    assert len(src4) == 1
    assert_safe(ans4, "Flow 4 answer")
    assert_sources_safe(src4, "Flow 4 sources")
    print("  -> Passed. 0 leaks, single exact match with public URL verified.")

    # Flow 5: "Give me the 2023 May Physics question paper"
    print("\n[Flow 5] 'Give me the 2023 May Physics question paper'")
    res5 = await handle_message("Give me the 2023 May Physics question paper", student_id="test_priv_5")
    ans5 = res5.get("answer", "")
    src5 = res5.get("sources", [])
    assert "Physics" in ans5 and "2023 May" in ans5
    assert PUBLIC_FIRST_YEAR_URL in ans5
    assert len(src5) == 1
    assert_safe(ans5, "Flow 5 answer")
    assert_sources_safe(src5, "Flow 5 sources")
    print("  -> Passed. 0 leaks, single exact match with public URL verified.")

    # -------------------------------------------------------------------------
    # PART 2: Multi-Turn Candidate Selection Follow-up
    # -------------------------------------------------------------------------
    print("\n--- PART 2: Multi-Turn Academic Follow-up Paths ---")

    sess_id = create_session(student_id="test_priv_session")
    try:
        # Step A: Ask for list
        reqA = AskRequest(message="Give me the Physics question papers", student_id="test_priv_session", session_id=sess_id)
        resA = await ask_endpoint(reqA)
        assert_safe(resA["answer"], "Step A answer")
        assert_sources_safe(resA.get("sources", []), "Step A sources")

        # Step B: Follow-up with specific paper "2023 May"
        reqB = AskRequest(message="2023 May", student_id="test_priv_session", session_id=sess_id)
        resB = await ask_endpoint(reqB)
        ansB = resB["answer"]
        assert "2023 May" in ansB
        assert PUBLIC_FIRST_YEAR_URL in ansB
        assert_safe(ansB, "Step B answer")
        assert_sources_safe(resB.get("sources", []), "Step B sources")
        print("  -> Passed. Candidate follow-up '2023 May' resolved with zero leaks.")

        # Step C: Ask for Physics Unit 1 notes (ambiguous)
        reqC = AskRequest(message="Give me Physics Unit 1 notes", student_id="test_priv_session", session_id=sess_id)
        resC = await ask_endpoint(reqC)
        assert_safe(resC["answer"], "Step C answer")

        # Step D: Follow-up with ordinal "the first one"
        reqD = AskRequest(message="the first one", student_id="test_priv_session", session_id=sess_id)
        resD = await ask_endpoint(reqD)
        assert_safe(resD["answer"], "Step D answer")
        assert_sources_safe(resD.get("sources", []), "Step D sources")
        print("  -> Passed. Ordinal follow-up 'the first one' resolved with zero leaks.")

        # Step E: Transition cleanly from pending question paper to fresh Unit 1 Laser notes
        reqE1 = AskRequest(message="Give me the Physics question papers", student_id="test_priv_session", session_id=sess_id)
        await ask_endpoint(reqE1)
        reqE2 = AskRequest(message="Give me Physics Unit 1 Lasers notes", student_id="test_priv_session", session_id=sess_id)
        resE2 = await ask_endpoint(reqE2)
        assert "Lasers" in resE2["answer"]
        assert_safe(resE2["answer"], "Step E2 answer")
        assert_sources_safe(resE2.get("sources", []), "Step E2 sources")
        print("  -> Passed. Fresh doc request clears pending question paper context with zero leaks.")
    finally:
        delete_session(sess_id)

    # -------------------------------------------------------------------------
    # PART 3: End-to-End POST /ask Endpoint Verification
    # -------------------------------------------------------------------------
    print("\n--- PART 3: End-to-End POST /ask Endpoint Verification ---")
    for q in [
        "Give me the Mathematics notes",
        "Give me Unit 1 Mathematics notes",
        "Give me the Physics question papers",
        "Give me Physics Unit 1 Lasers notes",
        "Give me the 2023 May Physics question paper"
    ]:
        req = AskRequest(message=q, student_id="test_http_user")
        res = await ask_endpoint(req)
        assert_safe(res.get("answer", ""), f"HTTP /ask [{q}] answer")
        assert_sources_safe(res.get("sources", []), f"HTTP /ask [{q}] sources")
        print(f"  [OK] POST /ask '{q}' -> 0 path leaks, public URL verified.")

    print("\n" + "=" * 70)
    print("ALL PRIVACY & PATH SAFETY REGRESSION TESTS PASSED (100%)!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
