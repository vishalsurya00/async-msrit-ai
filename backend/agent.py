"""
Agent routing module for MSRIT AI.
Implements rule-based intent classification and dispatches requests to RAG or audited MCP tools.
"""
from typing import Dict, Any, List, Optional
import re
import asyncio
import sys
from backend import mcp_client
from backend import rag

BRANCH_KEYWORDS = {
    "cse": "Computer Science & Engineering",
    "ise": "Information Science & Engineering",
    "aiml": "Artificial Intelligence & Machine Learning",
    "ai & ml": "Artificial Intelligence & Machine Learning",
    "ece": "Electronics & Communication Engineering",
    "eee": "Electrical & Electronics Engineering",
    "mech": "Mechanical Engineering",
    "civil": "Civil Engineering",
    "biotech": "Biotechnology",
    "bt": "Biotechnology",
    "chemical": "Chemical Engineering",
}


def _extract_profile_data(message: str) -> Dict[str, Any]:
    """Extract branch and semester from text like 'I am in AIML 3rd semester'."""
    lower = message.lower()
    data = {}

    # Extract semester
    sem_match = re.search(r'\b(?:sem(?:ester)?\s*(\d+)|(\d+)(?:st|nd|rd|th)?\s*sem(?:ester)?)\b', lower)
    if sem_match:
        sem_str = sem_match.group(1) or sem_match.group(2)
        try:
            data["semester"] = int(sem_str)
        except ValueError:
            pass

    # Extract branch
    for code, full_name in BRANCH_KEYWORDS.items():
        if re.search(r'\b' + re.escape(code) + r'\b', lower) or full_name.lower() in lower:
            data["branch"] = code.upper()
            break

    return data


def _extract_subject_for_summary(message: str) -> Optional[str]:
    """Extract subject from requests like 'summarize chemistry' or 'give a summary of physics'."""
    lower = message.lower()
    common_subjects = ["chemistry", "physics", "mathematics", "maths", "esc", "c programming", "mechanics"]
    for sub in common_subjects:
        if sub in lower:
            return sub.capitalize()
    
    # Fallback pattern: summarize <subject>
    m = re.search(r'(?:summarize|summary of|overview of)\s+([a-zA-Z\s]+)', lower)
    if m:
        cleaned = m.group(1).strip().split()[0]
        if cleaned not in ["the", "my", "our", "all"]:
            return cleaned.capitalize()
    return None


async def handle_message(message: str, student_id: str) -> Dict[str, Any]:
    """
    Rule-based intent dispatcher.
    Routes queries to:
    1. Student profile update (e.g. 'I am in AIML 3rd sem')
    2. Branch/Department lookup (e.g. 'Who is HOD of CSE?', 'Where is AIML branch?')
    3. Club lookup (e.g. 'Tell me about robotics club', 'List cultural clubs')
    4. Subject notes summarization (e.g. 'Summarize chemistry notes')
    5. Notes Q&A via local RAG (fallback default)
    """
    clean_msg = message.strip()
    clean_id = student_id.strip() if student_id else "anonymous"
    lower_msg = clean_msg.lower()

    # 1. Profile update intent
    profile_indicators = ["i am in", "i'm in", "my branch is", "update my", "set my branch", "set my semester"]
    has_profile_indicator = any(p in lower_msg for p in profile_indicators)
    extracted_profile = _extract_profile_data(clean_msg)

    if has_profile_indicator and (extracted_profile.get("branch") or extracted_profile.get("semester")):
        res = await mcp_client.call_tool(
            "update_student_profile",
            student_id=clean_id,
            branch=extracted_profile.get("branch"),
            semester=extracted_profile.get("semester")
        )
        if isinstance(res, dict) and res.get("error"):
            answer = f"Could not update profile: {res.get('error')}"
        else:
            branch_info = extracted_profile.get('branch', 'Not specified')
            sem_info = extracted_profile.get('semester', 'Not specified')
            answer = f"Profile updated successfully for {clean_id}:\n- Branch: {branch_info}\n- Semester: {sem_info}"

        return {
            "answer": answer,
            "action_taken": "update_student_profile",
            "sources": []
        }

    # 2. Branch / Department lookup intent
    branch_query_indicators = ["hod", "head of department", "branch", "department", "where is", "location of"]
    is_branch_query = any(ind in lower_msg for ind in branch_query_indicators)
    # Check if a branch is mentioned
    detected_branch = None
    for code, full_name in BRANCH_KEYWORDS.items():
        if re.search(r'\b' + re.escape(code) + r'\b', lower_msg):
            detected_branch = code.upper()
            break

    if is_branch_query and (detected_branch or "branch" in lower_msg or "department" in lower_msg):
        query_val = detected_branch or clean_msg
        res = await mcp_client.call_tool("lookup_branch", query=query_val)

        if isinstance(res, dict) and res.get("code"):
            answer = (
                f"**Department Information - {res.get('name')} ({res.get('code')})**\n"
                f"- Stream: {res.get('stream')}\n"
                f"- Head of Department (HOD): {res.get('hod_name') or 'N/A'}\n"
                f"- Location: {res.get('location') or 'Campus Main Block'}"
            )
        elif isinstance(res, dict) and res.get("error"):
            answer = f"Branch lookup error: {res.get('error')}"
        else:
            answer = f"No department details found matching '{query_val}'. Currently, static branch records are empty or not configured."

        return {
            "answer": answer,
            "action_taken": "lookup_branch",
            "sources": []
        }

    # 3. Club lookup intent
    club_indicators = ["club", "clubs", "society", "societies", "chapter"]
    if any(ind in lower_msg for ind in club_indicators):
        category = None
        if "technical" in lower_msg:
            category = "Technical"
        elif "cultural" in lower_msg:
            category = "Cultural"

        # Search term excluding 'club', 'clubs'
        query_val = re.sub(r'\b(clubs?|societ(?:y|ies)|tell me about|list|show)\b', '', lower_msg).strip()
        res = await mcp_client.call_tool("lookup_club", query=query_val if query_val else None, category=category)

        if isinstance(res, list) and res:
            lines = ["**Student Clubs & Societies at MSRIT:**"]
            for c in res:
                lead = f" (Lead: {c.get('lead_name')})" if c.get('lead_name') else ""
                lines.append(f"- **{c.get('name')}** [{c.get('category')}]{lead}: {c.get('description') or ''}")
            answer = "\n".join(lines)
        elif isinstance(res, dict) and res.get("error"):
            answer = f"Club search error: {res.get('error')}"
        else:
            answer = "No clubs found matching your search. Campus club entries can be populated in the clubs database table."

        return {
            "answer": answer,
            "action_taken": "lookup_club",
            "sources": []
        }

    # 4. Summarization intent
    summary_indicators = ["summarize", "summary of", "overview of", "key points of", "give a summary"]
    if any(ind in lower_msg for ind in summary_indicators):
        subject = _extract_subject_for_summary(clean_msg)
        if subject:
            # Run blocking Ollama call in background thread
            res = await asyncio.to_thread(rag.summarize_notes, subject=subject)
            return {
                "answer": res.get("summary", "No summary generated."),
                "action_taken": "summarize_notes",
                "sources": res.get("sources", [])
            }

    # 5. Default Fallback: RAG QA grounded in notes
    res = await asyncio.to_thread(rag.answer_question, query=clean_msg, student_id=clean_id)
    return {
        "answer": res.get("answer", "No answer could be generated."),
        "action_taken": "answer_question",
        "sources": res.get("sources", [])
    }
