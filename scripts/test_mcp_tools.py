"""
Dedicated Test Suite for Step 4A: MCP Tool Registry for RIT NEXUS.
Verifies all 6 core MCP capabilities:
1. lookup_department (+ legacy alias lookup_branch)
2. lookup_club
3. search_academic_documents
4. get_academic_document
5. get_student_profile
6. update_student_profile

Also tests:
- Tool discovery and registry reflection
- Unknown department, club, and document handling
- AI&ML vs CSE(AI&ML) strict disambiguation (in lookup and student profile)
- Invalid tool arguments and controlled MCP error handling
- Audit logging verification in PostgreSQL
"""
import asyncio
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.mcp_client import mcp_session, call_tool, list_tools, get_mcp_client
from backend.memory import delete_student_profile
from db.connection import get_connection


async def run_mcp_tests():
    print("=" * 75)
    print("RIT NEXUS — STEP 4A: MCP TOOL REGISTRY REGRESSION SUITE")
    print("=" * 75)
    test_count = 0
    start_time = time.perf_counter()

    async with mcp_session():
        # -------------------------------------------------------------
        # 1. MCP Tool Discovery and Registry Reflection
        # -------------------------------------------------------------
        print("\n--- 1. Testing MCP Tool Discovery & Registration ---")
        tools = await list_tools()
        print(f"Registered MCP Tools: {tools}")
        
        required_tools = [
            "lookup_department",
            "lookup_club",
            "search_academic_documents",
            "get_academic_document",
            "get_student_profile",
            "update_student_profile",
        ]
        for rt in required_tools:
            assert rt in tools, f"Required MCP tool '{rt}' is not registered on MCP server"
            test_count += 1
            print(f"  [OK] Tool registered: {rt}")

        # Check backwards-compatible alias
        assert "lookup_branch" in tools, "Legacy alias 'lookup_branch' must remain registered"
        test_count += 1
        print("  [OK] Legacy alias registered: lookup_branch")

        # -------------------------------------------------------------
        # 2. Department Lookup (lookup_department & lookup_branch)
        # -------------------------------------------------------------
        print("\n--- 2. Testing Department Lookup ---")
        
        # Exact code
        cse_dept = await call_tool("lookup_department", query="CSE")
        assert isinstance(cse_dept, dict), f"Expected dict, got: {cse_dept}"
        assert cse_dept.get("code") == "CSE"
        assert "China Appala Naidu" in cse_dept.get("hod_name", "")
        assert "DES Block" in cse_dept.get("location", "")
        assert "Computer Science" in cse_dept.get("stream", "")
        test_count += 1
        print(f"  [OK] lookup_department('CSE'): {cse_dept['name']} (HOD: {cse_dept['hod_name']})")

        # Query by alias
        ce_dept = await call_tool("lookup_department", query="civil")
        assert isinstance(ce_dept, dict)
        assert ce_dept.get("code") == "CE"
        test_count += 1
        print(f"  [OK] lookup_department('civil'): {ce_dept['name']} ({ce_dept['code']})")

        # Query via legacy alias lookup_branch
        me_dept = await call_tool("lookup_branch", query="Mechanical")
        assert isinstance(me_dept, dict)
        assert me_dept.get("code") == "ME"
        test_count += 1
        print(f"  [OK] lookup_branch('Mechanical'): {me_dept['name']} ({me_dept['code']})")

        # -------------------------------------------------------------
        # 3. Unknown Department Handling
        # -------------------------------------------------------------
        print("\n--- 3. Testing Unknown Department Handling ---")
        res_unk_dept = await call_tool("lookup_department", query="NonExistentDepartment999")
        assert res_unk_dept is None, f"Expected None for unknown department, got: {res_unk_dept}"
        test_count += 1
        print("  [OK] lookup_department('NonExistentDepartment999') -> None (Clean Not Found)")

        res_empty_dept = await call_tool("lookup_department", query="")
        assert res_empty_dept is None, f"Expected None for empty query, got: {res_empty_dept}"
        test_count += 1
        print("  [OK] lookup_department('') -> None (Clean Not Found)")

        # -------------------------------------------------------------
        # 4. AI&ML vs CSE(AI&ML) Disambiguation
        # -------------------------------------------------------------
        print("\n--- 4. Testing AI&ML vs CSE(AI&ML) Distinction ---")
        aiml_dept = await call_tool("lookup_department", query="AI&ML")
        assert isinstance(aiml_dept, dict)
        assert aiml_dept.get("code") == "AI&ML"
        assert "Apex Block" in aiml_dept.get("location", "")
        assert "Jagadish" in aiml_dept.get("hod_name", "")
        test_count += 1
        print(f"  [OK] AI&ML department: Code={aiml_dept['code']}, Loc={aiml_dept['location']}, HOD={aiml_dept['hod_name']}")

        cse_aiml_dept = await call_tool("lookup_department", query="CSE(AI&ML)")
        assert isinstance(cse_aiml_dept, dict)
        assert cse_aiml_dept.get("code") == "CSE(AIML)"
        assert "Multipurpose Block" in cse_aiml_dept.get("location", "")
        assert "Dr. Siddesh G. M." in cse_aiml_dept.get("hod_name", "")
        test_count += 1
        print(f"  [OK] CSE(AI&ML) department: Code={cse_aiml_dept['code']}, Loc={cse_aiml_dept['location']}, HOD={cse_aiml_dept['hod_name']}")

        # Ensure complete divergence between the two
        assert aiml_dept["code"] != cse_aiml_dept["code"]
        assert aiml_dept["location"] != cse_aiml_dept["location"]
        assert aiml_dept["hod_name"] != cse_aiml_dept["hod_name"]
        test_count += 1
        print("  [OK] AI&ML and CSE(AI&ML) have verified distinct code, location, and HOD")

        # -------------------------------------------------------------
        # 5. Club Lookup (lookup_club)
        # -------------------------------------------------------------
        print("\n--- 5. Testing Club Lookup ---")
        coderit = await call_tool("lookup_club", query="CodeRIT")
        assert isinstance(coderit, list) and len(coderit) >= 1
        assert coderit[0].get("name") == "CodeRIT"
        assert "Technical" in coderit[0].get("category", "")
        test_count += 1
        print(f"  [OK] lookup_club('CodeRIT'): Found {coderit[0]['name']} [{coderit[0]['category']}]")

        tech_clubs = await call_tool("lookup_club", category="Technical")
        assert isinstance(tech_clubs, list) and len(tech_clubs) > 1
        test_count += 1
        print(f"  [OK] lookup_club(category='Technical'): Found {len(tech_clubs)} technical clubs")

        # -------------------------------------------------------------
        # 6. Unknown Club Handling
        # -------------------------------------------------------------
        print("\n--- 6. Testing Unknown Club Handling ---")
        unknown_club = await call_tool("lookup_club", query="UnknownClubXYZ123")
        assert isinstance(unknown_club, list)
        assert len(unknown_club) == 0
        test_count += 1
        print("  [OK] lookup_club('UnknownClubXYZ123') -> [] (Clean empty list)")

        # -------------------------------------------------------------
        # 7. Academic Document Search (search_academic_documents)
        # -------------------------------------------------------------
        print("\n--- 7. Testing Academic Document Search ---")
        math_docs = await call_tool("search_academic_documents", subject="Mathematics", unit=1)
        assert isinstance(math_docs, list) and len(math_docs) >= 1
        for d in math_docs:
            assert "document_id" in d
            assert "title" in d
            assert d.get("subject") == "Mathematics"
            assert d.get("unit") == 1
            assert d.get("is_local") is True
        test_count += 1
        print(f"  [OK] search_academic_documents(subject='Mathematics', unit=1): Found {len(math_docs)} local document(s)")

        # Search by query keyword
        laplace_docs = await call_tool("search_academic_documents", query="Laplace")
        assert isinstance(laplace_docs, list) and len(laplace_docs) >= 1
        assert "Laplace" in laplace_docs[0]["title"]
        test_count += 1
        print(f"  [OK] search_academic_documents(query='Laplace'): Found '{laplace_docs[0]['title']}'")

        # No match document search
        empty_docs = await call_tool("search_academic_documents", subject="Astrophysics", unit=99)
        assert isinstance(empty_docs, list) and len(empty_docs) == 0
        test_count += 1
        print("  [OK] search_academic_documents(subject='Astrophysics', unit=99) -> [] (Clean empty list)")

        # -------------------------------------------------------------
        # 8. Academic Document Retrieval (get_academic_document)
        # -------------------------------------------------------------
        print("\n--- 8. Testing Academic Document Retrieval ---")
        first_doc_id = math_docs[0]["document_id"]
        exact_doc = await call_tool("get_academic_document", document_id=first_doc_id)
        assert isinstance(exact_doc, dict)
        assert exact_doc.get("document_id") == first_doc_id
        assert exact_doc.get("subject") == "Mathematics"
        assert exact_doc.get("is_local") is True
        test_count += 1
        print(f"  [OK] get_academic_document('{first_doc_id}'): Title='{exact_doc['title']}', Local={exact_doc['is_local']}")

        # -------------------------------------------------------------
        # 9. Missing Document Handling
        # -------------------------------------------------------------
        print("\n--- 9. Testing Missing Document Handling ---")
        missing_doc = await call_tool("get_academic_document", document_id="nonexistent-doc-99999")
        assert missing_doc is None, f"Expected None for missing document, got: {missing_doc}"
        test_count += 1
        print("  [OK] get_academic_document('nonexistent-doc-99999') -> None (Clean Not Found)")

        missing_empty = await call_tool("get_academic_document", document_id="")
        assert missing_empty is None, f"Expected None for empty document_id, got: {missing_empty}"
        test_count += 1
        print("  [OK] get_academic_document('') -> None (Clean Not Found)")

        # -------------------------------------------------------------
        # 10. Student Profile Retrieval & Update
        # -------------------------------------------------------------
        print("\n--- 10. Testing Student Profile Retrieval & Update ---")
        test_sid = "test_mcp_student_regression_4a"
        delete_student_profile(test_sid)

        # Before update -> None
        prof_before = await call_tool("get_student_profile", student_id=test_sid)
        assert prof_before is None, f"Expected None before creation, got: {prof_before}"
        test_count += 1
        print(f"  [OK] get_student_profile('{test_sid}') before update -> None")

        # Create profile with CSE(AI&ML)
        up_res1 = await call_tool(
            "update_student_profile",
            student_id=test_sid,
            name="Sovereign Student",
            college="Ramaiah Institute of Technology",
            degree="B.E.",
            branch="CSE(AI&ML)",
            semester=3,
            cgpa=9.12
        )
        assert isinstance(up_res1, dict)
        assert up_res1.get("name") == "Sovereign Student"
        assert up_res1.get("branch") == "CSE(AI&ML)"
        assert up_res1.get("semester") == 3
        assert up_res1.get("cgpa") == 9.12
        test_count += 1
        print(f"  [OK] update_student_profile: created profile with branch='{up_res1['branch']}', cgpa={up_res1['cgpa']}")

        # Retrieve profile
        prof_after = await call_tool("get_student_profile", student_id=test_sid)
        assert isinstance(prof_after, dict)
        assert prof_after.get("student_id") == test_sid
        assert prof_after.get("name") == "Sovereign Student"
        assert prof_after.get("branch") == "CSE(AI&ML)"
        assert prof_after.get("semester") == 3
        assert prof_after.get("updated_at") is not None
        test_count += 1
        print(f"  [OK] get_student_profile: retrieved persistent profile (updated_at: {prof_after['updated_at']})")

        # Partial update (PATCH behavior): update only semester and cgpa, leaving name/branch intact
        up_res2 = await call_tool(
            "update_student_profile",
            student_id=test_sid,
            semester=4,
            cgpa=9.35
        )
        assert isinstance(up_res2, dict)
        assert up_res2.get("name") == "Sovereign Student"
        assert up_res2.get("branch") == "CSE(AI&ML)"
        assert up_res2.get("semester") == 4
        assert up_res2.get("cgpa") == 9.35
        test_count += 1
        print("  [OK] update_student_profile: partial update preserved existing fields (PATCH semantics verified)")

        # Verify AI&ML branch normalization in student profile
        test_sid_aiml = "test_mcp_student_aiml_4a"
        delete_student_profile(test_sid_aiml)
        up_aiml = await call_tool(
            "update_student_profile",
            student_id=test_sid_aiml,
            branch="AI&ML"
        )
        assert up_aiml.get("branch") == "AI&ML"
        test_count += 1
        print(f"  [OK] Profile branch normalization: 'AI&ML' stored as '{up_aiml['branch']}'")

        # Clean up test student profiles
        delete_student_profile(test_sid)
        delete_student_profile(test_sid_aiml)
        print("  [OK] Cleaned up temporary test student profiles")

        # -------------------------------------------------------------
        # 11. Invalid Tool Arguments & MCP Error Handling
        # -------------------------------------------------------------
        print("\n--- 11. Testing Invalid Tool Arguments & Error Handling ---")
        
        # Missing required parameter or invalid tool name
        err_unk_tool = await call_tool("nonexistent_tool_12345")
        assert isinstance(err_unk_tool, dict) and "error" in err_unk_tool
        test_count += 1
        print(f"  [OK] Call unknown tool -> controlled error dict: {err_unk_tool['error']}")

        # Invalid argument type (e.g. string for integer parameter)
        err_arg_type = await call_tool("search_academic_documents", unit="not-an-int")
        assert isinstance(err_arg_type, dict) and "error" in err_arg_type
        test_count += 1
        print(f"  [OK] Call with invalid argument type -> controlled error dict: {err_arg_type['error']}")

        # Empty student_id in update_student_profile
        err_empty_sid = await call_tool("update_student_profile", student_id="")
        assert isinstance(err_empty_sid, dict) and "error" in err_empty_sid
        test_count += 1
        print(f"  [OK] update_student_profile(student_id='') -> controlled error dict: {err_empty_sid['error']}")

        # Server liveness check after errors: ensure server and connection did not crash
        post_err_check = await call_tool("lookup_department", query="ECE")
        assert isinstance(post_err_check, dict) and post_err_check.get("code") == "ECE"
        test_count += 1
        print("  [OK] MCP Server session remained healthy and responsive after multiple error conditions")

    # -------------------------------------------------------------
    # 12. PostgreSQL Audit Log Verification
    # -------------------------------------------------------------
    print("\n--- 12. Testing PostgreSQL Audit Logging ---")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tool_name, student_id, success, COUNT(*)
        FROM audit_log
        WHERE tool_name IN (
            'lookup_department', 'lookup_branch', 'lookup_club', 
            'search_academic_documents', 'get_academic_document', 
            'get_student_profile', 'update_student_profile'
        )
        GROUP BY tool_name, student_id, success
        ORDER BY tool_name;
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "No audit_log entries found for MCP tools"
    
    # Check that lookup_department was logged
    cur.execute("SELECT COUNT(*) FROM audit_log WHERE tool_name = 'lookup_department';")
    dept_audit_count = cur.fetchone()[0]
    assert dept_audit_count > 0, f"Expected audit_log entries for 'lookup_department', found {dept_audit_count}"
    test_count += 1
    print(f"  [OK] PostgreSQL audit_log verified: {dept_audit_count} 'lookup_department' audited entries")

    # Check student profile update audit
    cur.execute("SELECT COUNT(*) FROM audit_log WHERE tool_name = 'update_student_profile';")
    prof_audit_count = cur.fetchone()[0]
    assert prof_audit_count > 0
    test_count += 1
    print(f"  [OK] PostgreSQL audit_log verified: {prof_audit_count} 'update_student_profile' audited entries")

    cur.close()
    conn.close()

    elapsed = time.perf_counter() - start_time
    print("\n" + "=" * 75)
    print(f"ALL {test_count} MCP TOOL REGISTRY TESTS PASSED SUCCESSFULLY in {elapsed:.2f}s!")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_mcp_tests())
