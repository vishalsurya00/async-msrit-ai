"""
End-to-end CLI Smoke Test for MSRIT AI.
Tests:
1. Academic RAG (notes chunk retrieval + Ollama local LLM generation)
2. Campus Directory MCP tool (lookup_branch)
3. Clubs Directory MCP tool (lookup_club)
4. Student Profile Memory update (update_student_profile)
5. Audit log verification
"""
import sys
import asyncio
from pathlib import Path
import json

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import handle_message
from backend.mcp_client import get_mcp_client
from db.connection import get_connection


async def run_smoke_test():
    student_id = "1MS24CS001"
    
    test_cases = [
        {
            "num": 1,
            "category": "Academic RAG (Notes Retrieval + Ollama)",
            "message": "Explain corrosion mechanisms and factors affecting corrosion",
        },
        {
            "num": 2,
            "category": "Campus Directory / MCP Tool (lookup_branch)",
            "message": "Where is the CSE department office and who is the HOD?",
        },
        {
            "num": 3,
            "category": "Clubs Directory / MCP Tool (lookup_club)",
            "message": "Tell me about CodeRIT and which branches can join",
        },
        {
            "num": 4,
            "category": "Student Profile Memory (update_student_profile)",
            "message": "I am in 2nd semester AIML branch",
        },
    ]

    print("=" * 70)
    print("MSRIT AI - END-TO-END CLI SMOKE TEST")
    print("=" * 70)

    for tc in test_cases:
        print(f"\n--- [Question {tc['num']}] {tc['category']} ---")
        print(f"User Message: \"{tc['message']}\"")
        print(f"Student ID: {student_id}")
        
        try:
            res = await handle_message(tc["message"], student_id)
            print(f"Action Taken: {res.get('action_taken')}")
            print(f"Answer:\n{res.get('answer')}")
            sources = res.get("sources", [])
            if sources:
                print("Sources:")
                for s in sources:
                    print(f"  - {s.get('file_path')} (Subject: {s.get('subject')})")
            else:
                print("Sources: None")
        except Exception as e:
            print(f"ERROR: {e}")

    # Verify student_profile in PostgreSQL
    print("\n--- Verifying Student Profile in PostgreSQL ---")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT student_id, branch, semester, stream, cycle FROM student_profile WHERE student_id = %s;", (student_id,))
    profile = cur.fetchone()
    if profile:
        print(f"Profile found: ID={profile[0]}, Branch={profile[1]}, Semester={profile[2]}, Stream={profile[3]}, Cycle={profile[4]}")
    else:
        print("No profile found for", student_id)

    # Count audit_log entries
    print("\n--- Verifying Audit Log Entries in PostgreSQL ---")
    cur.execute("SELECT COUNT(*) FROM audit_log;")
    audit_count = cur.fetchone()[0]
    print(f"Total audit_log entries: {audit_count}")

    # Show recent audit_log rows
    cur.execute("SELECT id, timestamp, tool_name, student_id, success, result_summary FROM audit_log ORDER BY id DESC LIMIT 5;")
    recent_logs = cur.fetchall()
    print("Recent Audit Logs:")
    for row in recent_logs:
        print(f"  [ID {row[0]}] {row[1]} | Tool: {row[2]} | Student: {row[3]} | Success: {row[4]} | Summary: {row[5]}")

    cur.close()
    conn.close()

    # Clean up persistent MCP client
    client = get_mcp_client()
    await client.close()
    print("\n" + "=" * 70)
    print("SMOKE TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
