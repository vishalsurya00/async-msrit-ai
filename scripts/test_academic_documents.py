"""
Regression and verification test suite for Step 2:
Academic Knowledge + Academic Document Retrieval.
"""
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.agent import classify_intent, handle_message
from backend.mcp_client import mcp_session
from backend.documents import (
    detect_document_query_params,
    search_academic_documents,
    format_document_response
)


async def main():
    print("=" * 70)
    print("MSRIT AI STEP 2: ACADEMIC & DOCUMENT RETRIEVAL REGRESSION TESTS")
    print("=" * 70)

    # 1. Intent routing tests
    print("\n--- 1. Testing Intent Routing Precision ---")
    academic_queries = [
        "Explain Laplace Transform",
        "What is recursion?",
        "Explain Unit 1 Mathematics",
        "What is a linked list?",
        "What is a pointer in C?",
        "Explain sorting algorithms",
        "Explain this topic from my notes",
        "What is the difference between stack and queue?"
    ]
    for q in academic_queries:
        res = classify_intent(q)
        assert res["type"] == "academic", f"Failed: '{q}' was classified as {res['type']}"
        print(f"[OK] Academic: '{q}' -> {res['type']}")

    doc_queries = [
        "Give me Maths Unit 1 PDF",
        "I want Physics notes",
        "Find C programming question papers",
        "Give me the C programming lab manual",
        "Show me Unit 2 notes",
        "Download the C programming PDF",
        "Give me the PDF for Laplace Transform",
        "Give me Unit 2",
        "Give me the maths PDF"
    ]
    for q in doc_queries:
        res = classify_intent(q)
        assert res["type"] == "document_retrieval", f"Failed: '{q}' was classified as {res['type']}"
        print(f"[OK] Document: '{q}' -> {res['type']}")

    mixed_q = "Give me Maths Unit 1 PDF and explain Laplace Transform"
    res_m = classify_intent(mixed_q)
    assert res_m["type"] == "mixed_academic_document", f"Failed mixed: '{mixed_q}' -> {res_m['type']}"
    print(f"[OK] Mixed: '{mixed_q}' -> {res_m['type']}")

    # Regression queries
    reg_queries = [
        ("Who is CSE HOD?", "department"),
        ("Where is CSE?", "department"),
        ("Tell me about CSE.", "department"),
        ("SecuRIT", "club"),
        ("Who are you?", "identity"),
        ("Who r u?", "identity"),
        ("Who am I?", "memory_query"),
        ("What is my name?", "memory_query"),
        ("What is my CGPA?", "memory_query"),
        ("My name is Vishal", "memory_update"),
        ("AI&ML", "department"),
        ("CSE(AI&ML)", "department")
    ]
    for q, exp in reg_queries:
        res = classify_intent(q)
        assert res["type"] == exp, f"Failed regression: '{q}' expected {exp}, got {res['type']}"
        print(f"[OK] Regression: '{q}' -> {res['type']}")

    # 2. Database & MCP Document Search Verification
    print("\n--- 2. Testing Database Document Search ---")
    math_docs = search_academic_documents(subject="Mathematics", unit=1, document_type="notes")
    assert len(math_docs) > 0, "No Mathematics Unit 1 notes found"
    for d in math_docs:
        assert d["is_local"] is True, f"File {d['local_file_path']} not found locally on disk"
    print(f"[OK] Found {len(math_docs)} local Mathematics Unit 1 notes")

    phy_docs = search_academic_documents(subject="Physics", unit=2, document_type="notes")
    assert len(phy_docs) == 1, f"Expected 1 Physics Unit 2 document, got {len(phy_docs)}"
    assert phy_docs[0]["title"] == "Unit 2 (Quantum Mechanics)"
    print(f"[OK] Exact match: {phy_docs[0]['title']}")

    laplace_docs = search_academic_documents(subject="Mathematics", query="laplace")
    assert len(laplace_docs) >= 1, "Expected Laplace transform notes"
    assert "Laplace" in laplace_docs[0]["title"]
    print(f"[OK] Found Laplace document: {laplace_docs[0]['title']}")

    # 3. End-to-End handle_message API flows
    print("\n--- 3. Testing End-to-End handle_message API Flows ---")
    async with mcp_session():
        # Clarification 1: missing subject
        res = await handle_message("Give me Unit 2", student_id="test_user")
        assert "Which subject" in res["answer"], f"Expected subject clarification: {res['answer']}"
        print("[OK] Clarification (missing subject) verified")

        # Clarification 2: generic PDF type
        res = await handle_message("Give me the maths PDF", student_id="test_user")
        assert "Mathematics notes, a question paper" in res["answer"], f"Expected type clarification: {res['answer']}"
        print("[OK] Clarification (generic type) verified")

        # Exact document retrieval
        res = await handle_message("Give me Physics Unit 2 notes", student_id="test_user")
        assert "Unit 2 (Quantum Mechanics)" in res["answer"]
        assert len(res["sources"]) == 1
        print("[OK] Physics Unit 2 document retrieval verified")

        # Missing document
        res = await handle_message("Show me C programming lab manual", student_id="test_user")
        assert "not currently available in the local MSRIT knowledge base" in res["answer"]
        print("[OK] Honest missing document response verified")

        # Mixed query
        res = await handle_message("Give me Maths Unit 1 PDF and explain Laplace Transform", student_id="test_user")
        assert "Academic Explanation" in res["answer"]
        assert "Mathematics Unit 1" in res["answer"]
        print("[OK] Mixed query retrieval + explanation verified")

    print("\n" + "=" * 70)
    print("ALL 30+ STEP 2 TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
