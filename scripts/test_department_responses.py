"""
Comprehensive tests for department response formatting, intent classification, and end-to-end API.
Includes regression testing for:
1. ISE vs CSE alias disambiguation ("is" vs "ise" vs "cse")
2. ME disambiguation (preventing "how can you help me?" or "where is me?" from matching ME)
3. 3-state MCP handling (SUCCESS vs NOT FOUND vs SERVICE ERROR)
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import classify_intent, handle_message, detect_department_query_type
from backend import mcp_client


async def run_tests():
    print("=" * 70)
    print("STARTING DEPARTMENT AND ROUTING TESTS")
    print("=" * 70)
    test_count = 0

    # 1. Test detect_department_query_type
    assert detect_department_query_type("who is the hod of cse") == "hod"; test_count += 1
    assert detect_department_query_type("who is cse hod") == "hod"; test_count += 1
    assert detect_department_query_type("cse hod name") == "hod"; test_count += 1
    assert detect_department_query_type("where is cse") == "location"; test_count += 1
    assert detect_department_query_type("where is the cse department") == "location"; test_count += 1
    assert detect_department_query_type("what is the location of cse") == "location"; test_count += 1
    assert detect_department_query_type("cse department location") == "location"; test_count += 1
    assert detect_department_query_type("what stream is cse") == "stream"; test_count += 1
    assert detect_department_query_type("which stream does cse belong to") == "stream"; test_count += 1
    assert detect_department_query_type("tell me about cse department") == "full"; test_count += 1
    assert detect_department_query_type("give me cse department details") == "full"; test_count += 1
    assert detect_department_query_type("Where is CSE?") == "location"; test_count += 1
    assert detect_department_query_type("Where is Mechanical?") == "location"; test_count += 1
    assert detect_department_query_type("Where is Civil?") == "location"; test_count += 1
    assert detect_department_query_type("Where is AIML?") == "location"; test_count += 1
    assert detect_department_query_type("Who is the CSE HOD and where is the department?") == "hod+location"; test_count += 1
    print(f"[OK] {test_count} detect_department_query_type tests PASSED")

    # 2. Test classify_intent & Disambiguation
    c_hod_dept = classify_intent("who is hod of cse dept")
    assert c_hod_dept.get("type") == "department", f"Expected 'department', got {c_hod_dept}"
    assert c_hod_dept.get("entity") == "CSE", f"Expected entity 'CSE', got {c_hod_dept.get('entity')}"
    assert c_hod_dept.get("query_type") == "hod"
    test_count += 1

    c_hod = classify_intent("who is the hod of cse?")
    assert c_hod.get("type") == "department", f"Expected 'department', got {c_hod}"
    assert c_hod.get("entity") == "CSE", f"Expected entity 'CSE', got {c_hod.get('entity')}"
    assert c_hod.get("query_type") == "hod"
    test_count += 1

    c_loc = classify_intent("where is cse?")
    assert c_loc.get("type") == "department", f"Expected 'department', got {c_loc}"
    assert c_loc.get("entity") == "CSE", f"Expected entity 'CSE', got {c_loc.get('entity')}"
    assert c_loc.get("query_type") == "location"
    test_count += 1

    c_ise_hod = classify_intent("who is hod of ise?")
    assert c_ise_hod.get("type") == "department", f"Expected 'department', got {c_ise_hod}"
    assert c_ise_hod.get("entity") == "ISE", f"Expected entity 'ISE', got {c_ise_hod.get('entity')}"
    assert c_ise_hod.get("query_type") == "hod"
    test_count += 1

    c_ise_loc = classify_intent("where is ise?")
    assert c_ise_loc.get("type") == "department", f"Expected 'department', got {c_ise_loc}"
    assert c_ise_loc.get("entity") == "ISE", f"Expected entity 'ISE', got {c_ise_loc.get('entity')}"
    assert c_ise_loc.get("query_type") == "location"
    test_count += 1

    c_mech_hod = classify_intent("who is hod of mechanical?")
    assert c_mech_hod.get("type") == "department", f"Expected 'department', got {c_mech_hod}"
    assert c_mech_hod.get("entity") == "ME", f"Expected entity 'ME', got {c_mech_hod.get('entity')}"
    assert c_mech_hod.get("query_type") == "hod"
    test_count += 1

    c_mech_loc = classify_intent("where is mechanical?")
    assert c_mech_loc.get("type") == "department", f"Expected 'department', got {c_mech_loc}"
    assert c_mech_loc.get("entity") == "ME", f"Expected entity 'ME', got {c_mech_loc.get('entity')}"
    assert c_mech_loc.get("query_type") == "location"
    test_count += 1

    # Ambiguous / Normal English tests
    c_help_me = classify_intent("how can you help me?")
    assert c_help_me.get("type") != "department" or c_help_me.get("entity") != "ME", f"Misidentified as ME: {c_help_me}"
    test_count += 1

    c_where_me = classify_intent("where is me?")
    assert c_where_me.get("type") != "department" or c_where_me.get("entity") != "ME", f"Misidentified as ME: {c_where_me}"
    test_count += 1

    c_id = classify_intent("who are you?")
    assert c_id.get("type") == "identity", f"Expected 'identity', got {c_id}"
    assert c_id.get("entity") != "ISE", f"Misidentified as ISE: {c_id}"
    test_count += 1

    c_stream = classify_intent("What stream is CSE?")
    assert c_stream.get("type") == "department"
    assert c_stream.get("query_type") == "stream"
    test_count += 1

    c_full = classify_intent("Tell me about CSE department")
    assert c_full.get("type") == "department"
    assert c_full.get("query_type") == "full"
    test_count += 1

    c_fac = classify_intent("Who is Dr Siddesh G M?")
    assert c_fac.get("type") == "faculty", f"Expected 'faculty', got {c_fac}"
    test_count += 1

    print("[OK] All classify_intent and disambiguation tests PASSED")

    # 3. Test handle_message output requirements
    print("\n--- Testing handle_message Outputs ---")

    # Test 1: Who are you?
    res1 = await handle_message("Who are you?", "test_user")
    ans1 = res1["answer"]
    assert "MSRIT AI" in ans1
    assert "academic assistant" in ans1
    test_count += 1

    # Test 2: who is hod of cse dept (Primary prompt query)
    res2 = await handle_message("who is hod of cse dept", "test_user")
    ans2 = res2["answer"]
    print("Test 2 'who is hod of cse dept' ->", ans2)
    assert "CSE HOD: Dr. R. China Appala Naidu" in ans2, f"Got: {ans2}"
    assert "ISE" not in ans2, f"Answer should not contain 'ISE': {ans2}"
    assert "Office Location" not in ans2, f"Answer should not contain 'Office Location': {ans2}"
    assert "Stream" not in ans2, f"Answer should not contain 'Stream': {ans2}"
    test_count += 1

    # Test 2b: who is the hod of cse?
    res2b = await handle_message("who is the hod of cse?", "test_user")
    ans2b = res2b["answer"]
    print("Test 2b 'who is the hod of cse?' ->", ans2b)
    assert ans2b == "CSE HOD: Dr. R. China Appala Naidu", f"Got: {ans2b}"
    test_count += 1

    # Test 3: where is cse?
    res3 = await handle_message("where is cse?", "test_user")
    ans3 = res3["answer"]
    print("Test 3 'where is cse?' ->", ans3)
    assert "CSE Department Location" in ans3, f"Got: {ans3}"
    assert "HOD:" not in ans3, f"Answer should not contain 'HOD:': {ans3}"
    assert "Stream:" not in ans3, f"Answer should not contain 'Stream:': {ans3}"
    test_count += 1

    # Test 3b: who is hod of ise?
    res3b = await handle_message("who is hod of ise?", "test_user")
    ans3b = res3b["answer"]
    print("Test 3b 'who is hod of ise?' ->", ans3b)
    assert "ISE HOD: Dr. Sumana M. S." in ans3b, f"Got: {ans3b}"
    assert "CSE" not in ans3b, f"Got: {ans3b}"
    test_count += 1

    # Test 4: What stream is CSE?
    res4 = await handle_message("What stream is CSE?", "test_user")
    ans4 = res4["answer"]
    print("Test 4 'What stream is CSE?' ->", ans4)
    assert "CSE Stream: Computer Science" in ans4, f"Got: {ans4}"
    assert "HOD:" not in ans4
    assert "Office Location" not in ans4
    test_count += 1

    # Test 5: Tell me about CSE department (Full response)
    res5 = await handle_message("Tell me about CSE department", "test_user")
    ans5 = res5["answer"]
    assert "Department Information — Computer Science & Engineering (CSE)" in ans5
    assert "HOD:" in ans5
    assert "Office Location:" in ans5
    assert "Stream:" in ans5
    test_count += 1

    # Test 6: Faculty name lookup (Dr Siddesh G M)
    res6 = await handle_message("Who is Dr Siddesh G M?", "test_user")
    ans6 = res6["answer"]
    assert "Faculty Information — Dr. Siddesh G. M." in ans6
    assert "CSE(AIML)" in ans6
    assert "CSE(CS)" in ans6
    test_count += 1

    # 4. Test NOT FOUND state
    print("\n--- Testing NOT FOUND State ---")
    with patch("backend.mcp_client.call_tool", return_value=None):
        res_nf = await handle_message("Where is ZZZ department?", "test_user")
        ans_nf = res_nf["answer"]
        print("Not found response ->", ans_nf)
        assert "No department details found matching" in ans_nf, f"Got: {ans_nf}"
        assert "temporarily unavailable" not in ans_nf
        test_count += 1

    # 5. Test MCP SERVICE ERROR state (NOT FOUND != SERVICE ERROR)
    print("\n--- Testing MCP SERVICE ERROR State ---")
    with patch("backend.mcp_client.call_tool", return_value={"error": "Simulated transport connection failure"}):
        res_err = await handle_message("who is hod of cse dept", "test_user")
        ans_err = res_err["answer"]
        print("Service error response ->", ans_err)
        assert "MSRIT knowledge service is temporarily unavailable" in ans_err, f"Got: {ans_err}"
        assert "No department details found" not in ans_err, f"Error should NOT say department not found: {ans_err}"
        test_count += 1

    print("\n" + "=" * 70)
    print(f"ALL {test_count} TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
