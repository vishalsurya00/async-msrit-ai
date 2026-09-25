"""
Agent routing module for MSRIT AI.
Implements a fast, deterministic intent router before RAG, dispatching queries to:
- Greeting / Conversation (no DB or RAG call)
- Student Profile Memory (query/update)
- Department Lookup (audited database tool)
- Club Lookup (audited database tool)
- Academic RAG / Summarization (grounded local notes Q&A)
- Unknown / Faculty directory placeholder (no blind RAG hallucination)
"""
from typing import Dict, Any, List, Optional
import re
import asyncio
import sys
from backend import mcp_client
from backend import rag
from backend.audit import log_action
from backend.info_lookup import (
    BRANCH_ALIASES,
    find_branch_code,
    get_club_lookup_map,
    lookup_faculty
)

AMBIGUOUS_BRANCHES = {"me"}

IDENTITY_PATTERNS = [
    r'\b(?:who\s+are\s+you|what\s+are\s+you|what\s+can\s+you\s+do|tell\s+me\s+about\s+yourself|what\s+is\s+msrit\s+ai|about\s+msrit\s+ai|introduce\s+yourself|who\s+made\s+you)\b'
]

GREETING_PATTERNS = [
    r'^(?:hi|hello|hey|hola|sup|yo)\b',
    r'^(?:good\s+(?:morning|afternoon|evening|day))\b',
    r'^(?:thanks|thank\s+you(?:\s+so\s+much)?|thanks\s+a\s+lot)\b',
    r'^(?:bye|goodbye|see\s+you|cya)\b'
]

MEMORY_UPDATE_PATTERNS = [
    r'\b(?:i\s+am\s+in|i\'m\s+in|my\s+branch\s+is|update\s+my|set\s+my\s+branch|set\s+my\s+semester)\b',
    r'\b(?:remember\s+that\s+i|remember\s+my)\b'
]

MEMORY_QUERY_PATTERNS = [
    r'\b(?:what\s+is\s+my\s+branch|what\s+branch\s+am\s+i\s+in)\b',
    r'\b(?:what\s+semester\s+am\s+i\s+in|which\s+semester\s+am\s+i\s+in)\b',
    r'\b(?:what\s+is\s+my\s+profile|show\s+my\s+profile|who\s+am\s+i|my\s+profile|my\s+details)\b'
]

DEPT_KEYWORDS = [
    r'\b(?:hod|hoda|head\s+of(?:\s+the)?(?:\s+department)?)\b',
    r'\b(?:department|dept)\b',
    r'\b(?:where\s+is|location(?:\s+of)?|office(?:\s+location)?|located)\b',
    r'\b(?:stream|which\s+stream|belongs?\s+to\s+which\s+stream)\b'
]

ACADEMIC_EXPLICIT_TERMS = [
    r'\b(?:notes|syllabus|curriculum|module|unit\s*\d*|chapter|topics?|concepts?)\b',
    r'\b(?:chemistry|physics|maths|mathematics|corrosion|laplace|electrochemistry|semiconductor|mechanisms?|transform)\b',
    r'\b(?:summarize|summary\s+of|overview\s+of)\b'
]

ACADEMIC_ACTION_TERMS = [
    r'\b(?:explain|derive|define|difference\s+between)\b'
]

FACULTY_PATTERNS = [
    r'\b(?:dr\.|dr\b|prof\.|prof\b|professor|dean|principal)\b'
]


class IntentResult(dict):
    """
    Subclass of dict that allows direct string comparison, e.g.:
    classify_intent(...) == "department" or classify_intent(...)["type"] == "department".
    """
    def __eq__(self, other):
        if isinstance(other, str):
            return self.get("type") == other
        return super().__eq__(other)


def detect_department_query_fields(query: str) -> List[str]:
    """
    Deterministically detects which department fields are requested in the query.
    Returns a list of fields from ['hod', 'location', 'stream'], or ['full'].
    """
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', query.lower())

    # HOD keywords: hod, head of department, head of the department, hod name, etc.
    has_hod = bool(re.search(
        r'\b(?:hod|hoda|head\s+of(?:\s+the)?\s+department|hod\s+name|name\s+of(?:\s+the)?\s+hod)\b',
        clean
    ))

    # LOCATION keywords: where, location, located, office
    # Crucial rule: "where is <branch>" or "where is" MUST mean LOCATION
    has_location = bool(re.search(
        r'\b(?:where(?:\s+is)?|location(?:\s+of)?|office(?:\s+location)?|located)\b',
        clean
    ))

    # STREAM keywords: stream, belongs to which stream, which stream
    has_stream = bool(re.search(
        r'\b(?:stream|which\s+stream|belongs?\s+to\s+which\s+stream)\b',
        clean
    ))

    fields = []
    if has_hod:
        fields.append("hod")
    if has_location:
        fields.append("location")
    if has_stream:
        fields.append("stream")

    if not fields:
        return ["full"]

    return fields


def detect_department_query_type(query: str) -> str:
    """
    Deterministic helper returning requested department field:
    'hod', 'location', 'stream', or 'full' (or joined with '+' if multiple).
    """
    fields = detect_department_query_fields(query)
    if len(fields) == 1:
        return fields[0]
    return "+".join(fields)


def format_department_response(res: Dict[str, Any], query_type_or_fields: Any) -> str:
    """
    Formats the department lookup response based on requested fields.
    For single field:
      - 'hod'      -> '{code} HOD: {hod_name}'
      - 'location' -> '{code} Department Location: {location}'
      - 'stream'   -> '{code} Stream: {stream}'
    For multiple fields: returns each requested field on a new line.
    For 'full': returns the complete department card.
    """
    code = (res.get("code") or "Department").strip()
    name = (res.get("name") or code).strip()
    hod = (res.get("hod_name") or "N/A").strip()
    loc = (res.get("location") or "Campus Main Block").strip()
    stream = (res.get("stream") or "N/A").strip()

    if isinstance(query_type_or_fields, list):
        fields = query_type_or_fields
    elif isinstance(query_type_or_fields, str) and "+" in query_type_or_fields:
        fields = query_type_or_fields.split("+")
    elif isinstance(query_type_or_fields, str):
        fields = [query_type_or_fields]
    else:
        fields = ["full"]

    if fields == ["full"]:
        return (
            f"**Department Information — {name} ({code})**\n"
            f"- **HOD:** {hod}\n"
            f"- **Office Location:** {loc}\n"
            f"- **Stream:** {stream}"
        )

    lines = []
    for f in fields:
        if f == "hod":
            lines.append(f"{code} HOD: {hod}")
        elif f == "location":
            lines.append(f"{code} Department Location: {loc}")
        elif f == "stream":
            lines.append(f"{code} Stream: {stream}")

    if lines:
        return "\n".join(lines)

    return (
        f"**Department Information — {name} ({code})**\n"
        f"- **HOD:** {hod}\n"
        f"- **Office Location:** {loc}\n"
        f"- **Stream:** {stream}"
    )


def _match_branch(raw: str, clean: str) -> Optional[str]:
    """
    Matches query to a canonical branch code with strict priority:
    1. Exact full string match (e.g. 'cse', 'ise', 'me', 'mechanical')
    2. Meaningful and unambiguous branch aliases sorted from longest to shortest
       (e.g. 'computer science and engineering', 'mechanical', 'cse', 'ise', 'ce')
    3. Ambiguous aliases (e.g. 'me') ONLY when context clearly indicates Mechanical Engineering.
       Never matches standalone English 'is' or 'me' (e.g. 'who are you', 'how can you help me', 'where is me').
    """
    # 1. Exact string match on the full cleaned message
    if clean in BRANCH_ALIASES:
        return BRANCH_ALIASES[clean]

    # 2. Priority check: Check all unambiguous aliases from longest to shortest
    sorted_aliases = [a for a in sorted(BRANCH_ALIASES.keys(), key=len, reverse=True) if a not in AMBIGUOUS_BRANCHES]
    for alias in sorted_aliases:
        pat = r'(?:\b|^)' + re.escape(alias) + r'(?:\b|$)'
        if re.search(pat, clean):
            return BRANCH_ALIASES[alias]

    # 3. Ambiguous 'me' matching ONLY with clear mechanical department context
    # Context must clearly indicate Mechanical Engineering (e.g. 'me dept', 'hod of me')
    # and NEVER match conversational queries like 'where is me?' or 'help me'.
    me_dept_pat = (
        r'(?:\b(?:hod|head)\s+(?:of\s+)?me\b'
        r'|\bme\s+(?:department|dept|branch|office|hod)\b'
        r'|\b(?:department|dept|branch)\s+of\s+me\b)'
    )
    if re.search(me_dept_pat, clean):
        return "ME"

    return None


def _match_club(clean: str) -> Optional[str]:
    """Matches query to a canonical club name from dynamically loaded database clubs."""
    club_map = get_club_lookup_map()
    for c_alias in sorted(club_map.keys(), key=len, reverse=True):
        pat = r'(?:\b|^)' + re.escape(c_alias) + r'(?:\b|$)'
        if re.search(pat, clean):
            return club_map[c_alias]
    return None


def _extract_profile_data(message: str) -> Dict[str, Any]:
    """Extract branch and semester from text like 'I am in AIML 3rd semester'."""
    lower = message.lower()
    data = {}

    sem_match = re.search(r'\b(?:sem(?:ester)?\s*(\d+)|(\d+)(?:st|nd|rd|th)?\s*sem(?:ester)?)\b', lower)
    if sem_match:
        sem_str = sem_match.group(1) or sem_match.group(2)
        try:
            data["semester"] = int(sem_str)
        except ValueError:
            pass

    clean = re.sub(r'[^\w\s\(\)&-]', ' ', lower).strip()
    branch_code = _match_branch(message, clean)
    if branch_code:
        data["branch"] = branch_code

    return data


def _extract_subject_for_summary(message: str) -> Optional[str]:
    """Extract subject from requests like 'summarize chemistry' or 'give a summary of physics'."""
    lower = message.lower()
    common_subjects = ["chemistry", "physics", "mathematics", "maths", "esc", "c programming", "mechanics", "corrosion"]
    for sub in common_subjects:
        if sub in lower:
            return sub.capitalize()

    m = re.search(r'(?:summarize|summary\s+of|overview\s+of)\s+(?:my\s+notes\s+on\s+|my\s+)?([a-zA-Z\s]+)', lower)
    if m:
        cleaned = m.group(1).strip().split()[0]
        if cleaned not in ["the", "my", "our", "all", "notes"]:
            return cleaned.capitalize()
    return None


def classify_intent(message: str) -> IntentResult:
    """
    Deterministic intent router implementing strict priority:
    1. Greeting / Conversation / Identity
    2. Memory (Update / Query)
    3. Faculty Lookup (HOD/Faculty by name)
    4. Department Lookup (field-specific or full)
    5. Club Lookup
    6. Academic RAG / Summarization
    7. Unknown / Faculty directory placeholder
    """
    raw = message.strip()
    low = raw.lower()
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', low).strip()

    # 1. Identity / Conversation
    for ip in IDENTITY_PATTERNS:
        if re.search(ip, clean):
            return IntentResult(type="identity", raw=raw)

    for gp in GREETING_PATTERNS:
        if re.search(gp, clean):
            words = clean.split()
            # Ensure it is a short conversational message and not followed by a dept query
            if len(words) <= 4 or not any(re.search(dk, clean) for dk in DEPT_KEYWORDS):
                return IntentResult(type="greeting", raw=raw)

    # 2. Memory
    for mp in MEMORY_UPDATE_PATTERNS:
        if re.search(mp, clean):
            return IntentResult(type="memory_update", raw=raw)
    for mq in MEMORY_QUERY_PATTERNS:
        if re.search(mq, clean):
            return IntentResult(type="memory_query", raw=raw)

    # 3. Faculty Lookup (specific named faculty members like 'Dr. Siddesh G. M.')
    matched_faculty = lookup_faculty(raw)
    if matched_faculty:
        return IntentResult(type="faculty", entity=matched_faculty["canonical_name"], data=matched_faculty)

    has_faculty = any(re.search(fp, clean) for fp in FACULTY_PATTERNS)
    has_dept_kw = any(re.search(dk, clean) for dk in DEPT_KEYWORDS)
    matched_branch = _match_branch(raw, clean)
    matched_club = _match_club(clean)
    has_club_word = bool(re.search(r'\b(?:clubs?|societ(?:y|ies))\b', clean))

    # 4. Department Lookup
    # Explicit department questions about a branch (e.g. 'CSE HOD', 'Where is CSE?', 'Mechanical Engineering location')
    if matched_branch and has_dept_kw:
        q_type = detect_department_query_type(raw)
        return IntentResult(type="department", entity=matched_branch, query_type=q_type)

    # Explicit questions mentioning 'department' or 'dept' even if branch code is not recognized (e.g. 'Where is ZZZ department?')
    dept_phrase = re.search(r'\b([a-zA-Z]+)\s+(?:department|dept)\b', clean) or re.search(r'\b(?:department|dept)\s+(?:of\s+)?([a-zA-Z]+)\b', clean)
    if dept_phrase and not matched_club and not has_club_word:
        cand = dept_phrase.group(1).strip()
        if cand not in {"the", "a", "an", "this", "that", "each", "every", "our", "all", "which"}:
            q_type = detect_department_query_type(raw)
            return IntentResult(type="department", entity=cand.upper(), query_type=q_type)

    # 5. Club Lookup
    # Specific named club queries (e.g. 'CodeRIT', 'What is CodeRIT?', 'SecuRIT', 'Tensor AI', 'TNT')
    if matched_club and not (matched_branch and has_dept_kw):
        return IntentResult(type="club", entity=matched_club)
    if has_club_word and not matched_branch:
        return IntentResult(type="club", entity=None)

    # 6. Academic RAG
    # Questions requesting explanations, notes, topics, or course concepts
    has_academic_explicit = any(re.search(ae, clean) for ae in ACADEMIC_EXPLICIT_TERMS)
    has_academic_action = any(re.search(aa, clean) for aa in ACADEMIC_ACTION_TERMS)

    if re.search(r'\b(?:summarize|summary\s+of)\b', clean):
        return IntentResult(type="summarize", raw=raw)

    if has_academic_explicit or has_academic_action:
        return IntentResult(type="academic", raw=raw)

    # Pure branch name / alias queries (e.g. 'Mechanical', 'CSE', 'Biotechnology', 'Mechanical Engineering')
    if matched_branch:
        q_type = detect_department_query_type(raw)
        return IntentResult(type="department", entity=matched_branch, query_type=q_type)

    # 7. Unknown / Unsupported
    if has_faculty:
        return IntentResult(type="faculty_unknown", raw=raw)

    return IntentResult(type="unknown", raw=raw)


async def handle_message(message: str, student_id: str) -> Dict[str, Any]:
    """
    Main message dispatcher.
    Classifies intent deterministically before calling RAG or audited tools.
    """
    clean_msg = message.strip()
    clean_id = student_id.strip() if student_id else "anonymous"

    intent = classify_intent(clean_msg)
    intent_type = intent["type"]

    # 1. IDENTITY / CONVERSATION
    if intent_type == "identity":
        reply = "I’m MSRIT AI, a local-first academic assistant for MSRIT. I can help with MSRIT departments, clubs, academic notes, and your student profile."
        log_action(
            tool_name="conversation",
            student_id=clean_id,
            parameters={"query": clean_msg},
            result_summary="Handled identity question without DB/RAG",
            success=True
        )
        return {
            "answer": reply,
            "action_taken": "conversation",
            "sources": []
        }

    # 1. GREETING / CONVERSATION
    if intent_type == "greeting":
        low = clean_msg.lower()
        if any(w in low for w in ["thanks", "thank you"]):
            reply = "You're welcome! Let me know if you need anything else regarding MSRIT."
        elif any(w in low for w in ["bye", "goodbye", "see you", "cya"]):
            reply = "Goodbye! Have a great day ahead at MSRIT! 👋"
        elif any(w in low for w in ["good morning", "good afternoon", "good evening", "good day"]):
            reply = "Hello! Good day! 👋 How can I assist you with MSRIT today?"
        else:
            reply = "Hi! 👋 How can I help you with MSRIT?"

        log_action(
            tool_name="conversation",
            student_id=clean_id,
            parameters={"query": clean_msg},
            result_summary="Handled greeting without DB/RAG",
            success=True
        )
        return {
            "answer": reply,
            "action_taken": "conversation",
            "sources": []
        }

    # 2. MEMORY UPDATE
    if intent_type == "memory_update":
        extracted_profile = _extract_profile_data(clean_msg)
        if extracted_profile.get("branch") or extracted_profile.get("semester"):
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

    # 2. MEMORY QUERY
    if intent_type == "memory_query":
        res = await mcp_client.call_tool("get_student_profile", student_id=clean_id)
        if isinstance(res, dict) and "error" in res:
            answer = "MSRIT knowledge service is temporarily unavailable. Please check that the local database and MCP service are running."
        elif isinstance(res, dict) and res.get("branch"):
            answer = (
                f"**Your Student Profile ({clean_id}):**\n"
                f"- **Branch:** {res.get('branch') or 'Not specified'}\n"
                f"- **Semester:** {res.get('semester') or 'Not specified'}\n"
                f"- **Stream:** {res.get('stream') or 'Not specified'}\n"
                f"- **Cycle:** {res.get('cycle') or 'Not specified'}"
            )
        else:
            answer = "You haven't set your profile yet. You can tell me something like 'I am in 2nd semester AIML' to set it up!"

        log_action(
            tool_name="get_student_profile",
            student_id=clean_id,
            parameters={"student_id": clean_id},
            result_summary="Retrieved student profile",
            success=True
        )
        return {
            "answer": answer,
            "action_taken": "get_student_profile",
            "sources": []
        }

    # 3. DEPARTMENT LOOKUP
    if intent_type == "department":
        target = intent.get("entity") or clean_msg
        query_type = intent.get("query_type") or detect_department_query_type(clean_msg)
        res = await mcp_client.call_tool("lookup_branch", query=target)

        # 1. SERVICE ERROR (MCP, transport, or process failure)
        if isinstance(res, dict) and "error" in res:
            answer = "MSRIT knowledge service is temporarily unavailable. Please check that the local database and MCP service are running."
        # 2. SUCCESS (lookup succeeded and branch record found)
        elif isinstance(res, dict) and res.get("code"):
            answer = format_department_response(res, query_type)
        # 3. NOT FOUND (lookup executed but no department matched)
        else:
            answer = f"No department details found matching '{target}'. Please specify a recognized branch name or code (e.g., CSE, ME, Civil, ECE)."

        return {
            "answer": answer,
            "action_taken": "lookup_branch",
            "sources": []
        }

    # 4. CLUB LOOKUP
    if intent_type == "club":
        target = intent.get("entity")
        category = None
        low = clean_msg.lower()
        if "technical" in low:
            category = "Technical"
        elif "cultural" in low:
            category = "Cultural"

        query_param = target if target else re.sub(r'\b(clubs?|societ(?:y|ies)|tell me about|what is|list|show)\b', '', low).strip()
        res = await mcp_client.call_tool("lookup_club", query=query_param if query_param else None, category=category)

        if isinstance(res, dict) and "error" in res:
            answer = "MSRIT knowledge service is temporarily unavailable. Please check that the local database and MCP service are running."
        else:
            clubs_list = res if isinstance(res, list) else ([res] if isinstance(res, dict) and res.get("name") else [])
            if clubs_list:
                if len(clubs_list) == 1:
                    c = clubs_list[0]
                    answer = (
                        f"**Club Information — {c.get('name')}**\n"
                        f"- **Category:** {c.get('category') or 'N/A'}\n"
                        f"- **Lead / Scope:** {c.get('lead_name') or 'Student Committee'}\n"
                        f"- **Description:** {c.get('description') or 'Campus student organization at MSRIT.'}"
                    )
                else:
                    lines = ["**Student Clubs & Societies at MSRIT:**"]
                    for c in clubs_list:
                        lead = f" (Lead: {c.get('lead_name')})" if c.get('lead_name') else ""
                        lines.append(f"- **{c.get('name')}** [{c.get('category')}]{lead}: {c.get('description') or ''}")
                    answer = "\n".join(lines)
            else:
                answer = "No clubs found matching your search. Campus club entries can be populated in the clubs database table."

        return {
            "answer": answer,
            "action_taken": "lookup_club",
            "sources": []
        }

    # 5. ACADEMIC SUMMARIZE
    if intent_type == "summarize":
        subject = _extract_subject_for_summary(clean_msg)
        if subject:
            res = await asyncio.to_thread(rag.summarize_notes, subject=subject)
            return {
                "answer": res.get("summary", "No summary generated."),
                "action_taken": "summarize_notes",
                "sources": res.get("sources", [])
            }

    # 5. ACADEMIC RAG QA
    if intent_type == "academic":
        res = await asyncio.to_thread(rag.answer_question, query=clean_msg, student_id=clean_id)
        return {
            "answer": res.get("answer", "No answer could be generated."),
            "action_taken": "answer_question",
            "sources": res.get("sources", [])
        }

    # 6. FACULTY LOOKUP
    if intent_type == "faculty":
        fdata = intent.get("data") or lookup_faculty(clean_msg)
        if fdata:
            cname = fdata.get("canonical_name", "Faculty")
            depts = fdata.get("departments", [])
            lines = [f"**Faculty Information — {cname}**", "Associated Department(s):"]
            for d in depts:
                lines.append(f"- **{d.get('name')} ({d.get('code')})** — HOD | Office: {d.get('location')} | Stream: {d.get('stream')}")
            answer = "\n".join(lines)
            log_action(
                tool_name="lookup_faculty",
                student_id=clean_id,
                parameters={"query": clean_msg, "faculty": cname},
                result_summary=f"Found faculty {cname} with {len(depts)} department(s)",
                success=True
            )
            return {
                "answer": answer,
                "action_taken": "lookup_faculty",
                "sources": []
            }

    # 7. FACULTY DIRECTORY PLACEHOLDER
    if intent_type == "faculty_unknown":
        answer = "I don't currently have a faculty directory for that person. I can help with MSRIT departments, clubs, academic notes, or your student profile."
        log_action(
            tool_name="faculty_directory_placeholder",
            student_id=clean_id,
            parameters={"query": clean_msg},
            result_summary="Faculty lookup unsupported - safe placeholder returned",
            success=True
        )
        return {
            "answer": answer,
            "action_taken": "unknown_faculty",
            "sources": []
        }

    # 6. UNKNOWN / UNSUPPORTED
    answer = "I’m not sure what you’re asking about. I can currently help with MSRIT departments, clubs, academic notes, and your student profile."
    log_action(
        tool_name="unknown_clarification",
        student_id=clean_id,
        parameters={"query": clean_msg},
        result_summary="Out-of-scope query - clarification returned without RAG",
        success=True
    )
    return {
        "answer": answer,
        "action_taken": "unknown_clarification",
        "sources": []
    }
