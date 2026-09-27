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
from typing import Dict, Any, List, Optional, Tuple
import re
import asyncio
import sys
import time
from backend import mcp_client
from backend import rag
from backend.agentic import run_agentic_workflow
from backend.audit import log_action
from backend.info_lookup import (
    BRANCH_ALIASES,
    find_branch_code,
    get_club_lookup_map,
    lookup_faculty
)
from backend.documents import (
    detect_document_query_params,
    search_academic_documents,
    format_document_response
)
from backend.memory import (
    format_single_field_response,
    format_profile_overview,
    format_preferences_response,
    validate_and_normalize_profile_fields,
    normalize_canonical_branch
)
from backend.knowledge import (
    format_academic_context_response,
    format_recommended_clubs_response
)

AMBIGUOUS_BRANCHES = {"me"}

IDENTITY_PATTERNS = [
    r'\b(?:who\s+are\s+you|who\s+r\s+u|who\s+are\s+u|what\s+are\s+you|what\s+can\s+you\s+do|tell\s+me\s+about\s+yourself|what\s+is\s+msrit\s+ai|about\s+msrit\s+ai|introduce\s+yourself|who\s+made\s+you)\b'
]

GREETING_PATTERNS = [
    r'^(?:hi|hello|hey|hola|sup|yo)\b',
    r'^(?:good\s+(?:morning|afternoon|evening|day))\b',
    r'^(?:thanks|thank\s+you(?:\s+so\s+much)?|thanks\s+a\s+lot)\b',
    r'^(?:bye|goodbye|see\s+you|cya)\b'
]

EXPLICIT_PROFILE_UPDATE_PATTERNS = [
    r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:my\s+)?(?:profile|branch|department|dept|semester|sem|cgpa|gpa|year|college|degree|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\b',
    r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:semester|sem|branch|dept|department|cgpa|gpa|year|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\s+(?:to|with|as|is|=)\b',
    r'\b(?:my\s+branch|my\s+semester|my\s+sem|my\s+cgpa|my\s+gpa|my\s+name|my\s+college|my\s+degree|my\s+year|my\s+preference|my\s+main\s+focus|my\s+focus\s+subject)\s*(?:is|to|as|with|:=|:|:=|=)\b',
    r'\b(?:remember\s+that\s+)?(?:i\s+prefer|i\s+like)\s+(?:concise|short|brief|direct|detailed|long|thorough|in-depth|in\s+depth)\b',
    r'\b(?:remember\s+that\s+)?my\s+main\s+focus\s+is\b',
]

MEMORY_UPDATE_PATTERNS = [
    r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:my\s+)?(?:profile|branch|department|dept|semester|sem|cgpa|gpa|year|college|degree|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\b',
    r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:semester|sem|branch|dept|department|cgpa|gpa|year|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\s+(?:to|with|as|is|=)\b',
    r'\b(?:my\s+name\s+is|my\s+name\'s)\b',
    r'\b(?:you\s+can\s+call\s+me|call\s+me)\b',
    r'\b(?:my\s+cgpa\s+is|my\s+gpa\s+is|my\s+current\s+cgpa\s+is)\b',
    r'\b(?:with\s+cgpa|cgpa\s*[:=]|gpa\s*[:=])\b',
    r'\b(?:i\s+scored\s+[\d\w\.]+\s*(?:cgpa|gpa)?)\b',
    r'\b(?:my\s+branch\s+is|my\s+branch\s*:)\b',
    r'\b(?:my\s+semester\s+is|my\s+sem\s+is|my\s+current\s+semester\s+is)\b',
    r'\b(?:my\s+college\s+is|my\s+degree\s+is|my\s+stream\s+is|my\s+cycle\s+is)\b',
    r'\b(?:i\s+am\s+studying|i\'m\s+studying|i\s+study\s+at)\b',
    r'\b(?:i\s+am\s+pursuing|i\'m\s+pursuing|currently\s+pursuing)\b',
    r'\b(?:i\s+belong\s+to)\b',
    r'\b(?:i\s+am\s+in|i\'m\s+in)\b',
    r'\b(?:i\s+am\s+a\s+\d+(?:st|nd|rd|th)?\s+year\s+student|i\s+completed\s+my\s+\d+(?:st|nd|rd|th)?\s+year|i\s+am\s+currently\s+in\s+my\s+\d+(?:st|nd|rd|th)?\s+year)\b',
    r'\b(?:i\s+am\s+a\s+student\s+of)\b',
    r'\b(?:remember\s+that\s+i|remember\s+my)\b',
    r'\b(?:remember\s+that\s+)?(?:i\s+prefer|i\s+like)\s+(?:concise|short|brief|direct|detailed|long|thorough|in-depth|in\s+depth)\b',
    r'\b(?:remember\s+that\s+)?my\s+main\s+focus\s+is\b',
    r'\b(?:branch\s*[:=]|semester\s*[:=]|sem\s*[:=]|stream\s*[:=]|cycle\s*[:=]|cgpa\s*[:=]|college\s*[:=]|degree\s*[:=]|year\s*[:=]|name\s*[:=]|preference\s*[:=]|focus\s*[:=])\b'
]

MEMORY_QUERY_PATTERNS = [
    r'\b(?:who\s+am\s+i|who\s+i\s+am|tell\s+me\s+who\s+i\s+am|tell\s+me\s+about\s+myself|what\s+do\s+you\s+know\s+about\s+me|what\s+do\s+u\s+know\s+about\s+me|show\s+my\s+profile|what\s+is\s+my\s+profile|^my\s+profile$|^my\s+details$)\b',
    r'\b(?:(?:what|which)\s+(?:is\s+my\s+name|name\s+do\s+i\s+have)|tell\s+me\s+my\s+name)\b',
    r'\b(?:(?:what|which)\s+(?:is\s+my\s+branch|branch\s+am\s+i\s+(?:in|studying(?:\s+in)?)|branch\s+do\s+i\s+(?:have|belong\s+to))|tell\s+me\s+my\s+branch)\b',
    r'\b(?:(?:what|which)\s+(?:is\s+my\s+sem(?:ester)?|sem(?:ester)?\s+am\s+i\s+(?:in|studying(?:\s+in)?)|sem(?:ester)?\s+do\s+i\s+have)|tell\s+me\s+my\s+sem(?:ester)?)\b',
    r'\b(?:(?:what|which)\s+(?:is\s+my\s+(?:cgpa|gpa|grade|score)|(?:cgpa|gpa|grade|score)\s+do\s+i\s+have)|tell\s+me\s+my\s+(?:cgpa|gpa|grade|score))\b',
    r'\b(?:which\s+college\s+do\s+i\s+study\s+in|what\s+college\s+do\s+i\s+study\s+in|what\s+is\s+my\s+college|where\s+do\s+i\s+study)\b',
    r'\b(?:what\s+course\s+am\s+i\s+pursuing|what\s+degree\s+am\s+i\s+pursuing|what\s+is\s+my\s+degree|what\s+is\s+my\s+course)\b',
    r'\b(?:what|show|tell\s+me)\s+(?:are\s+)?(?:my\s+)?preferences?\b',
    r'\bwhat\s+preferences\s+do\s+you\s+(?:remember|have)\s+(?:about\s+me)?\b',
    r'\b(?:what|which)\s+(?:response\s+style|explanation\s+style)\s+do\s+i\s+prefer\b',
    r'\bwhat\s+(?:subject\s+am\s+i\s+focusing\s+on|is\s+my\s+focus\s+subject)\b',
]


def detect_profile_query_field(query: str) -> str:
    """
    Detects which specific profile field a user is querying, or 'full' for overall profile.
    """
    low = query.lower()
    if re.search(r'\b(?:response\s+style|explanation\s+style)\b', low):
        return "explanation_style"
    if re.search(r'\b(?:focus\s+subject|subject\s+am\s+i\s+focusing\s+on)\b', low):
        return "focus_subject"
    if re.search(r'\b(?:preferences?|preference)\b', low):
        return "preferences"
    if re.search(r'\b(?:name)\b', low):
        return "name"
    if re.search(r'\b(?:cgpa|gpa|grade|score)\b', low):
        return "cgpa"
    if re.search(r'\b(?:branch)\b', low):
        return "branch"
    if re.search(r'\b(?:sem(?:ester)?)\b', low):
        return "semester"
    if re.search(r'\b(?:year)\b', low):
        return "year"
    if re.search(r'\b(?:college|institution|university)\b', low):
        return "college"
    if re.search(r'\b(?:course|degree)\b', low):
        return "degree"
    return "full"

DEPT_KEYWORDS = [
    r'\b(?:hod|hoda|heads?|leading|leader|person\s+leading|head\s+of(?:\s+the)?(?:\s+department)?)\b',
    r'\b(?:department|dept)\b',
    r'\b(?:where\s+is|location(?:\s+of)?|office(?:\s+location)?|located|where\s+to\s+go|where\s+should\s+i\s+go)\b',
    r'\b(?:stream|which\s+stream|belongs?\s+to\s+which\s+stream)\b'
]

DOCUMENT_REQUEST_KEYWORDS = [
    r'\b(?:pdf|download|lab\s+manual|lab\s+record|question\s+papers?|previous\s+year\s+papers?|pyqs?|cie\s+papers?)\b',
    r'\b(?:give\s+me|i\s+want|show\s+me|find|get|send|download|provide)\b.*\b(?:notes?|pdf|question\s+papers?|pyqs?|lab\s+manual|syllabus|document|file)\b',
    r'\b(?:unit\s*[-_]?\s*(?:\d+|i{1,3}|iv|v))\s*(?:notes?|pdf|file|document|paper)?\b',
    r'\b(?:maths?|physics|chemistry|c\s+programming|civil|mechanical)\s+(?:notes?|pdf|question\s+papers?|pyqs?|lab\s+manual|syllabus|material|materials)\b',
    r'\b(?:give\s+me|show\s+me|find|get|download)\s+(?:the\s+)?(?:maths?|physics|chemistry|c\s+programming)\b',
    r'\b(?:give\s+me|show\s+me|find|get)\s+unit\s*[-_]?\s*(?:\d+|i{1,3}|iv|v)\b',
    r'\b(?:what|which)\s+(?:[a-zA-Z\s\(\)&+-]+)?(?:materials?|documents?|notes?|resources?)\s+(?:should\s+i\s+study|are\s+relevant|cover)\b',
    r'\b(?:material|materials|documents?)\s+(?:to\s+study|should\s+i\s+study)\b',
    r'\b(?:which|what)\s+[a-zA-Z\s\(\)&+-]+\s+(?:documents?|materials?|resources?|notes?)\s+(?:are\s+relevant|should\s+i\s+study)\b'
]

ACADEMIC_EXPLANATION_KEYWORDS = [
    r'\b(?:explain|definition\s+of|define|derive|derivation|what\s+is\s+(?:a|an|the)?|what\s+are|teach\s+me|how\s+does.*work|how\s+do|difference\s+between|concept\s+of|algorithm\s+for|sorting\s+algorithms?|recursion|pointers?|linked\s+list|stack\s+and\s+queue)\b',
    r'\b(?:explain\s+unit\s*\d+|explain\s+this\s+concept|explain\s+this\s+topic|explain\s+laplace)\b',
    r'\bexplain\s+laplace\s+transform\b'
]

ACADEMIC_EXPLICIT_TERMS = [
    r'\b(?:notes|syllabus|curriculum|module|unit\s*\d*|chapter|topics?|concepts?)\b',
    r'\b(?:chemistry|physics|maths|mathematics|corrosion|laplace|electrochemistry|semiconductor|mechanisms?|transform)\b',
    r'\b(?:summarize|summary\s+of|overview\s+of)\b',
    r'\b(?:what\s+should\s+i\s+study|help\s+me\s+plan\s+what\s+to\s+study|what\s+to\s+study|what\s+material\s+should\s+i\s+study|what\s+should\s+i\s+prepare)\b'
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

    # HOD keywords: hod, head of department, head of the department, hod name, who heads, person leading, etc.
    has_hod = bool(re.search(
        r'\b(?:hod|hoda|heads?|leading|leader|person\s+leading|head\s+of(?:\s+the)?(?:\s+department)?|hod\s+name|name\s+of(?:\s+the)?\s+hod)\b',
        clean
    ))

    # LOCATION keywords: where, location, located, office, where should i go, where to go
    has_location = bool(re.search(
        r'\b(?:where(?:\s+is)?|location(?:\s+of)?|office(?:\s+location)?|located|where\s+should\s+i\s+go|where\s+to\s+go|where\s+do\s+i\s+go|how\s+to\s+reach)\b',
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


def _call_qwen_grounded(question: str, facts: Dict[str, Any], response_type: str) -> Optional[str]:
    """
    Synchronous worker querying local Qwen 2.5:7B via Ollama.
    Acts as a natural-language interpreter strictly grounded in verified database facts.
    """
    import requests
    from backend.rag import OLLAMA_URL, OLLAMA_MODEL

    code = (facts.get("code") or "").strip()
    name = (facts.get("name") or code).strip().replace("", "-")
    hod = (facts.get("hod_name") or "").strip()
    loc = (facts.get("location") or "").strip()
    stream = (facts.get("stream") or "").strip()

    facts_lines = []
    if name:
        facts_lines.append(f"- Department: {name} ({code})" if code else f"- Department: {name}")

    if response_type == "hod":
        if hod:
            facts_lines.append(f"- Head of Department (HOD): {hod}")
        field_instruction = "The user is asking specifically about who leads or heads the department. Focus strictly on the HOD."
    elif response_type == "location":
        if loc:
            facts_lines.append(f"- Office Location: {loc}")
        field_instruction = "The user is asking specifically about the department's location or where to find it. Focus strictly on the location."
    elif response_type == "stream":
        if stream:
            facts_lines.append(f"- Academic Stream: {stream}")
        field_instruction = "The user is asking specifically about the academic stream. Focus strictly on the stream."
    elif "+" in response_type:
        fields = [f.strip() for f in response_type.split("+")]
        if "hod" in fields and hod:
            facts_lines.append(f"- Head of Department (HOD): {hod}")
        if "location" in fields and loc:
            facts_lines.append(f"- Office Location: {loc}")
        if "stream" in fields and stream:
            facts_lines.append(f"- Academic Stream: {stream}")
        field_instruction = f"The user is asking about {', '.join(fields)}. Cover only these requested fields."
    else:
        # Full / general query
        if hod:
            facts_lines.append(f"- Head of Department (HOD): {hod}")
        if loc:
            facts_lines.append(f"- Office Location: {loc}")
        if stream:
            facts_lines.append(f"- Academic Stream: {stream}")
        field_instruction = "The user wants general or full department information. Provide a concise, natural overview covering the verified facts."

    facts_str = "\n".join(facts_lines)

    prompt = (
        "You are MSRIT AI, a knowledgeable, friendly, and helpful campus assistant for Ramaiah Institute of Technology students.\n\n"
        "USER QUESTION:\n"
        f"{question}\n\n"
        "VERIFIED MSRIT FACTS:\n"
        f"{facts_str}\n\n"
        "INSTRUCTIONS:\n"
        "- Directly answer the user's question in a natural, fluent, and conversational sentence.\n"
        "- Adapt your wording and sentence structure naturally to match how the user asked their question.\n"
        "- Rely ONLY on the verified facts above. Never invent, assume, or alter any names, titles, locations, floors, or details.\n"
        "- Do not extrapolate or add unverified details (such as curriculum descriptions, history, or rankings).\n"
        f"- {field_instruction}\n"
        "- Do not repeat the same rigid sentence formula. Avoid sounding like a canned database template or machine printout.\n"
        "- Never mention 'database', 'MCP', 'verified facts', 'system', 'prompt', 'retrieval', or internal data structures. Speak naturally as MSRIT AI.\n"
        "- If a requested fact is not present in the verified facts, say: 'I don't have that information in the available MSRIT data.'\n"
        "- Keep the answer concise (1-2 sentences for specific questions, 2-3 sentences for general overviews).\n\n"
        "Answer:"
    )

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 120
                }
            },
            timeout=30
        )
        resp.raise_for_status()
        reply = resp.json().get("response", "").strip()
        return reply if reply else None
    except Exception as e:
        print(f"[Qwen Grounding] Ollama call error: {e}", file=sys.stderr)
        return None


async def generate_grounded_response(question: str, facts: Dict[str, Any], response_type: str) -> str:
    """
    Generate a grounded natural language response from verified database facts using local Qwen 2.5:7B.
    If Ollama/Qwen is unavailable, errors, or times out, safely falls back to deterministic format_department_response().
    """
    try:
        print(f"[Qwen Grounding] Interpreting verified facts for question: {question!r} (type: {response_type})", file=sys.stderr)
        qwen_answer = await asyncio.to_thread(_call_qwen_grounded, question, facts, response_type)
        if qwen_answer:
            print(f"[Qwen Grounding] Success: {qwen_answer!r}", file=sys.stderr)
            return qwen_answer
        print("[Qwen Grounding] Received empty response from Qwen. Using deterministic fallback.", file=sys.stderr)
    except Exception as e:
        print(f"[Qwen Grounding] Exception ({e}). Using deterministic fallback.", file=sys.stderr)

    return format_department_response(facts, response_type)


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
        pat = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
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


def _extract_profile_data(message: str) -> Tuple[Dict[str, Any], List[str]]:
    """
    Extracts all supported student profile fields from natural language or key-value formatted text:
    name, college, degree, branch, semester, year, stream, cycle, cgpa.
    Only extracts information explicitly provided by the user.
    Returns (extracted_dict, invalid_fields_list).
    """
    data: Dict[str, Any] = {}
    invalid_fields: List[str] = []
    lower = message.lower()
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', lower).strip()

    # 1. Name
    m_name_cmd = re.search(
        r'\b(?:(?:update|change|set|save|record|add|modify|edit)\s+(?:my\s+)?name|(?:my\s+)?name)\s*(?:is|to|as|with|:=|:|:=|=)?\s*([a-zA-Z\s\.\'-]+?)(?:,|$|\b(?:and|with|branch|sem|semester|cgpa|college|degree|year|stream|cycle)\b)',
        message,
        re.I
    )
    m_name_kv = re.search(r'\bname\s*[:=]\s*([a-zA-Z\s\.\'-]+?)(?:,|$|\b(?:and|with|branch|sem|semester|cgpa|college|degree|year|stream|cycle)\b)', message, re.I)
    m_name_nat = re.search(r'\bmy\s+name\s+is\s+([a-zA-Z\s\.\'-]+?)(?:,|$|\.|\b(?:and|i\s+am|studying|currently|with|cgpa|branch|sem|semester|at)\b)', message, re.I)
    m_name_call = re.search(r'\b(?:you\s+can\s+call\s+me|call\s+me)\s+([a-zA-Z\s\.\'-]+?)(?:,|$|\.|\b(?:and|with|branch|sem|cgpa)\b)', message, re.I)
    raw_name = (m_name_cmd.group(1) if m_name_cmd else (m_name_kv.group(1) if m_name_kv else (m_name_nat.group(1) if m_name_nat else (m_name_call.group(1) if m_name_call else None))))

    # Natural "I am <Name>" pattern (e.g. "I am Vishal" or "I am Vishal Kumar")
    if not raw_name:
        m_name_iam = re.search(r'\b(?:i\s+am|i\'m)\s+([a-zA-Z\s\.\'-]+?)(?:,|$|\.|\b(?:and|with|branch|sem|semester|cgpa)\b)', message, re.I)
        if m_name_iam:
            cand = m_name_iam.group(1).strip()
            stopwords = {"a", "an", "the", "in", "studying", "pursuing", "currently", "at", "from", "looking", "searching", "not", "learning", "student", "msrit", "first", "second", "third", "fourth", "semester", "year", "be", "btech", "here", "done"}
            tokens = [t.lower() for t in cand.split() if t]
            if tokens and tokens[0] not in stopwords and not any(t in stopwords for t in tokens) and len(cand) >= 2:
                raw_name = cand

    if raw_name:
        clean_name = raw_name.strip(' .,;:-')
        if len(clean_name) >= 2 and clean_name.lower() not in {'not specified', 'a', 'an', 'the', 'msrit'}:
            data['name'] = clean_name

    # 2. CGPA
    m_cgpa_cmd = re.search(
        r'\b(?:(?:update|change|set|save|record|add|modify|edit)\s+(?:my\s+)?(?:current\s+)?(?:cgpa|gpa)|(?:my\s+)?(?:current\s+)?(?:cgpa|gpa))\s*(?:is|to|as|with|:=|:|:=|=)?\s*([^\s,;]+)',
        message,
        re.I
    )
    m_cgpa_kv = re.search(r'\b(?:cgpa|gpa)\s*[:=]\s*([^\s,;]+)', message, re.I)
    m_cgpa_nat = re.search(r'\b(?:i\s+scored|scored|with)\s+([^\s,;]+)\s*(?:cgpa|gpa)\b', message, re.I)
    m_cgpa_nat2 = re.search(r'\b([^\s,;]+)\s*(?:cgpa|gpa)\b', message, re.I)
    cgpa_val = (m_cgpa_cmd.group(1) if m_cgpa_cmd else (m_cgpa_kv.group(1) if m_cgpa_kv else (m_cgpa_nat.group(1) if m_cgpa_nat else (m_cgpa_nat2.group(1) if m_cgpa_nat2 else None))))

    if cgpa_val:
        raw_val = cgpa_val.strip(' .,;:-')
        try:
            val = float(raw_val)
            if 0.0 <= val <= 10.0:
                data['cgpa'] = round(val, 2)
            else:
                invalid_fields.append("cgpa")
        except ValueError:
            invalid_fields.append("cgpa")

    # 3. Semester
    # Supports: "update semester with 3", "update my semester with 3", "update semester to 3",
    # "change my semester to 3", "set semester to 3", "my semester is 3", "semester = 3", "in 3rd semester"
    m_sem_cmd = re.search(
        r'\b(?:(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:my\s+)?(?:semester|sem)|(?:my\s+)?(?:current\s+)?(?:semester|sem))\b\s*(?:is|to|as|with|:=|:|:=|=)?\s*([a-zA-Z0-9]+)\b',
        message,
        re.I
    )
    m_sem_kv = re.search(r'\b(?:semester|sem)\s*[:=]\s*([a-zA-Z0-9]+)', message, re.I)
    m_sem_nat = re.search(r'\b(?:in\s+)?(\d+)(?:st|nd|rd|th)?\s*(?:semester|sem)\b', message, re.I)
    m_sem_word = re.search(r'\b(?:in\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth)\s+(?:semester|sem)\b', message, re.I)

    sem_val = None
    if m_sem_cmd:
        cand = m_sem_cmd.group(1).strip(' .,;:-')
        if cand.lower() not in {"to", "with", "as", "is"}:
            sem_val = cand
    elif m_sem_kv:
        sem_val = m_sem_kv.group(1).strip(' .,;:-')
    elif m_sem_nat:
        sem_val = m_sem_nat.group(1).strip(' .,;:-')
    elif m_sem_word:
        sem_val = m_sem_word.group(1).strip(' .,;:-')

    if sem_val:
        clean_sem = sem_val.strip(' .,;:-').lower()
        word_to_num = {
            'first': 1, '1st': 1, 'one': 1,
            'second': 2, '2nd': 2, 'two': 2,
            'third': 3, '3rd': 3, 'three': 3,
            'fourth': 4, '4th': 4, 'four': 4,
            'fifth': 5, '5th': 5, 'five': 5,
            'sixth': 6, '6th': 6, 'six': 6,
            'seventh': 7, '7th': 7, 'seven': 7,
            'eighth': 8, '8th': 8, 'eight': 8,
        }
        try:
            if clean_sem in word_to_num:
                s_int = word_to_num[clean_sem]
            else:
                s_int = int(clean_sem)
            if 1 <= s_int <= 10:
                data['semester'] = s_int
            else:
                invalid_fields.append("semester")
        except ValueError:
            invalid_fields.append("semester")

    # 4. Year
    m_yr_cmd = re.search(
        r'\b(?:(?:update|change|set|save|record|add|modify|edit)\s+(?:my\s+)?year|(?:my\s+)?year)\b\s*(?:is|to|as|with|:=|:|:=|=)?\s*([a-zA-Z0-9]+)\b',
        message,
        re.I
    )
    m_yr_kv = re.search(r'\byear\s*[:=]\s*([a-zA-Z0-9]+)', message, re.I)
    m_yr_dig = re.search(r'\b(?:completed\s+my\s+|in\s+my\s+|currently\s+in\s+my\s+|in\s+|am\s+in\s+|a\s+)?(\d+)(?:st|nd|rd|th)\s+year\b', message, re.I)
    m_yr_word = re.search(r'\b(?:completed\s+my\s+|in\s+my\s+|currently\s+in\s+my\s+|in\s+|am\s+in\s+|a\s+)?(first|second|third|fourth)\s+year\b', message, re.I)
    word_map = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, '1st': 1, '2nd': 2, '3rd': 3, '4th': 4}

    yr_val = None
    if m_yr_cmd:
        cand = m_yr_cmd.group(1).strip(' .,;:-')
        if cand.lower() not in {"to", "with", "as", "is"}:
            yr_val = cand
    elif m_yr_kv:
        yr_val = m_yr_kv.group(1).strip(' .,;:-')
    elif m_yr_dig:
        yr_val = m_yr_dig.group(1).strip(' .,;:-')

    if re.search(r'\bcompleted\s+my\s+(?:first|1st)\s+year\b', lower):
        data['year'] = 2
    elif yr_val:
        clean_yr = yr_val.strip(' .,;:-').lower()
        try:
            if clean_yr in word_map:
                y_int = word_map[clean_yr]
            else:
                y_int = int(clean_yr)
            if 1 <= y_int <= 6:
                data['year'] = y_int
            else:
                invalid_fields.append("year")
        except ValueError:
            invalid_fields.append("year")
    elif m_yr_word and m_yr_word.group(1).lower() in word_map:
        data['year'] = word_map[m_yr_word.group(1).lower()]

    # 5. College
    m_col_kv = re.search(r'\b(?:college|institution)\s*[:=]\s*([a-zA-Z0-9\s\.\'-]+?)(?:,|$|\b(?:branch|sem|semester|stream|cycle|cgpa|degree|year)\b)', message, re.I)
    m_col_nat = re.search(r'\b(?:studying\s+in|study\s+at|student\s+at|student\s+of|at)\s+(msrit|ramaiah\s+institute\s+of\s+technology|ramaiah)\b', message, re.I)
    if m_col_kv:
        data['college'] = m_col_kv.group(1).strip()
    elif m_col_nat:
        data['college'] = 'MSRIT'

    # 6. Degree
    m_deg_kv = re.search(r'\bdegree\s*[:=]\s*([a-zA-Z\.\s]+?)(?:,|$|\b(?:with|branch|sem|semester|stream|cycle|cgpa|year)\b)', message, re.I)
    m_deg_nat = re.search(r'\b(?:pursuing|doing|studying\s+for|studying|for)\s+(be|b\.e\.|bachelor\s+of\s+engineering|btech|b\.tech|bachelor\s+of\s+technology|mtech|m\.tech|mca|mba|barch|b\.arch)\b', message, re.I)
    deg_val = m_deg_kv.group(1) if m_deg_kv else (m_deg_nat.group(1) if m_deg_nat else None)
    if deg_val:
        clean_deg = deg_val.strip().lower()
        if "bachelor of engineering" in clean_deg or clean_deg in ("be", "b.e."):
            data['degree'] = "BE"
        elif "bachelor of technology" in clean_deg or clean_deg in ("btech", "b.tech"):
            data['degree'] = "BTech"
        else:
            data['degree'] = clean_deg.upper().replace('.', '')

    # 7. Branch
    m_br_cmd = re.search(
        r'\b(?:(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:my\s+)?(?:branch|dept|department)|(?:my\s+)?(?:branch|dept|department))\s*(?:is|to|as|with|:=|:|:=|=)?\s*([a-zA-Z0-9\(\)&-]+(?:\s+[a-zA-Z0-9\(\)&-]+)*)',
        message,
        re.I
    )
    m_br_kv = re.search(r'\b(?:branch|dept|department)\s*[:=]\s*([a-zA-Z0-9\(\)&-]+(?:\s+[a-zA-Z0-9\(\)&-]+)*)', message, re.I)
    m_studying = re.search(
        r'\b(?:studying\s+in|student\s+of|pursuing\s+(?:a\s+degree\s+in|in)?|enrolled\s+in|i\s+am\s+in|i\'m\s+in)\s+([a-zA-Z0-9\(\)&-]+(?:\s+[a-zA-Z0-9\(\)&-]+)*)',
        message,
        re.I
    )

    raw_branch = None
    if m_br_cmd:
        cand = m_br_cmd.group(1).strip(' .,;:-')
        cand_tokens = cand.lower().split()
        cand_stop = {"am", "do", "is", "can", "should", "would", "in", "to", "with", "as", "my", "the", "a", "an", "what", "which", "where", "who", "how"}
        if cand_tokens and cand_tokens[0] not in cand_stop:
            raw_branch = cand
    elif m_br_kv:
        raw_branch = m_br_kv.group(1).strip(' .,;:-')
    elif m_studying:
        cand = m_studying.group(1).strip(' .,;:-')
        stopwords = {"a", "an", "the", "first", "second", "third", "fourth", "1st", "2nd", "3rd", "4th", "semester", "sem", "year", "college", "msrit"}
        tokens = [t.lower() for t in cand.split() if t]
        if tokens and tokens[0] not in stopwords:
            raw_branch = cand

    if not raw_branch:
        # Fallback to _match_branch
        b_code = _match_branch(message, clean)
        if b_code:
            raw_branch = b_code

    if raw_branch:
        norm_b = normalize_canonical_branch(raw_branch)
        if norm_b:
            data['branch'] = norm_b

    # 8. Stream
    m_str_kv = re.search(r'\bstream\s*[:=]\s*([a-zA-Z0-9\s&-]+?)(?:,|$|\b(?:cycle|sem|semester|branch|cgpa)\b)', message, re.I)
    m_str_nat = re.search(r'\b(?:my\s+)?stream\s+(?:is\s+)?([a-zA-Z0-9\s&-]+?)(?:,|$|\b(?:and|cycle|sem|semester|branch|cgpa)\b)', message, re.I)
    str_val = m_str_kv.group(1) if m_str_kv else (m_str_nat.group(1) if m_str_nat else None)
    if str_val:
        data['stream'] = str_val.strip()

    # 9. Cycle
    m_cyc_kv = re.search(r'\bcycle\s*[:=]\s*([a-zA-Z0-9\s-]+?)(?:,|$|\b(?:stream|sem|semester|branch|cgpa)\b)', message, re.I)
    m_cyc_nat = re.search(r'\b(?:my\s+)?cycle\s+(?:is\s+)?(physics|chemistry|chem|phy|p|c|no|none)\b', message, re.I)
    cyc_val = m_cyc_kv.group(1) if m_cyc_kv else (m_cyc_nat.group(1) if m_cyc_nat else None)
    if cyc_val:
        data['cycle'] = cyc_val.strip()

    # 10. Preferences (explanation_style, focus_subject)
    # Stored ONLY upon explicit user command or declaration
    is_negated_or_third_party = bool(
        re.search(r'\b(?:my\s+friend|others?|people)\s+prefers?\b', lower) or
        re.search(r'\b(?:don\'t|dont|do\s+not)\s+(?:understand|like|prefer)\b', lower) or
        re.search(r'\bi\s+(?:think\s+i\s+should|might|may)\s+focus\b', lower) or
        re.search(r'\bi\s+hate\s+long\b', lower) or
        re.search(r'\b(?:are\s+sometimes|is\s+sometimes)\s+easier\b', lower) or
        re.search(r'\bi\s+am\s+studying\s+[a-zA-Z\s]+\s+today\b', lower)
    )

    if not is_negated_or_third_party:
        # A. Explanation Style
        m_pref_style = (
            re.search(r'\b(?:remember\s+that\s+)?(?:i\s+prefer|i\s+like)\s+([a-zA-Z\s-]+?)(?:\s+(?:answers?|explanations?|responses?|style))?(?:,|$|\.|\b(?:and|with)\b)', message, re.I)
            or re.search(r'\b(?:set|change|update|record|save|switch)\s+(?:my\s+)?(?:explanation\s+)?(?:preference|style|response\s+style)\s+(?:to|as|is|=)\s*([a-zA-Z\s-]+?)(?:\s+(?:answers?|explanations?|responses?|style))?(?:,|$|\.|\b(?:and|with)\b)', message, re.I)
            or re.search(r'\b(?:preference|style)\s*[:=]\s*([a-zA-Z\s-]+?)(?:\s+(?:answers?|explanations?|responses?|style))?(?:,|$|\.|\b(?:and|with)\b)', message, re.I)
        )
        if m_pref_style:
            raw_style = m_pref_style.group(1).strip().lower()
            from backend.memory import normalize_preference_value
            norm_style, is_valid = normalize_preference_value("explanation_style", raw_style)
            if is_valid:
                if 'preferences' not in data:
                    data['preferences'] = {}
                data['preferences']['explanation_style'] = norm_style
            else:
                invalid_fields.append("explanation_style")

        # B. Focus Subject
        m_pref_focus = (
            re.search(r'\b(?:remember\s+that\s+)?(?:my\s+)?(?:main\s+)?focus\s+(?:subject\s+)?is\s+([a-zA-Z\s\(\)&+-]+?)(?:,|$|\.|\b(?:and|with)\b)', message, re.I)
            or re.search(r'\b(?:set|change|update|record|save)\s+(?:my\s+)?(?:focus|focus\s+subject)\s+(?:to|as|is|=)\s*([a-zA-Z\s\(\)&+-]+?)(?:,|$|\.|\b(?:and|with)\b)', message, re.I)
            or re.search(r'\bfocus\s+subject\s*[:=]\s*([a-zA-Z\s\(\)&+-]+?)(?:,|$|\.|\b(?:and|with)\b)', message, re.I)
        )
        if m_pref_focus:
            raw_subj = m_pref_focus.group(1).strip()
            from backend.memory import normalize_preference_value
            norm_subj, is_valid = normalize_preference_value("focus_subject", raw_subj)
            if is_valid:
                if 'preferences' not in data:
                    data['preferences'] = {}
                data['preferences']['focus_subject'] = norm_subj
            else:
                invalid_fields.append("focus_subject")

    return data, invalid_fields


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
    1. Identity / Conversation (MSRIT AI assistant identity)
    2. Memory Query (Student queries asking about their own profile details)
    3. Memory Update / Profile Statements
    4. Greeting
    5. Faculty Lookup (HOD/Faculty by name)
    6. Department Lookup (field-specific or full)
    7. Club Lookup
    8. Mixed Academic + Document Retrieval
    9. Document Retrieval
    10. Academic RAG / Summarization
    11. Unknown / Faculty directory placeholder
    """
    raw = message.strip() if message else ""
    if not raw:
        return IntentResult(type="empty", raw="")
    low = raw.lower()
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', low).strip()

    # 1. Identity (MSRIT AI assistant identity - never matches student queries like 'who am i')
    for ip in IDENTITY_PATTERNS:
        if re.search(ip, clean):
            return IntentResult(type="identity", raw=raw)

    # 1b. Preference Clear (Explicit request to clear/reset/forget preferences)
    if re.search(r'\b(?:clear|reset|forget|erase)\s+(?:my\s+)?preferences?\b', clean):
        return IntentResult(type="preference_clear", raw=raw)

    # 2. Memory Query (Student queries asking about their own profile details)
    for mq in MEMORY_QUERY_PATTERNS:
        if re.search(mq, clean):
            q_field = detect_profile_query_field(clean)
            return IntentResult(type="memory_query", raw=raw, query_field=q_field)

    # 3. Memory Update (Statements providing student profile information)
    # Profile update intent must take strict priority over department lookup
    # when the message contains explicit update/change/set language referring to my branch, my semester, etc.
    is_explicit_up = any(re.search(ep, clean) for ep in EXPLICIT_PROFILE_UPDATE_PATTERNS)
    is_mem_up = is_explicit_up or any(re.search(mp, clean) for mp in MEMORY_UPDATE_PATTERNS)
    extracted_prof, invalid_fields = _extract_profile_data(raw)
    has_dept_kw = any(re.search(dk, clean) for dk in DEPT_KEYWORDS)

    # Explicit profile update requests ALWAYS classify as memory_update
    if is_explicit_up:
        return IntentResult(type="memory_update", raw=raw, profile_data=extracted_prof, invalid_fields=invalid_fields)

    # Multi-Domain / Combined Agentic Queries:
    # 1. Profile Context + Academic / Document Question:
    # e.g., "I'm a CSE(AI&ML) student in semester 3. What Mathematics material should I study?"
    has_question_word = bool(re.search(r'\b(?:what|which|where|who|how|recommend|suggest|show\s+me|find|list|give\s+me)\b', clean) or '?' in raw)
    has_academic_topic = bool(re.search(r'\b(?:mathematics|maths|physics|chemistry|c\s+programming|notes|syllabus|material|study|subject|subjects|course|books)\b', clean))

    has_profile_ref = bool(re.search(r'\b(?:my\s+(?:profile|branch|dept|department)|based\s+on\s+my\s+profile|from\s+my\s+profile|look\s+up\s+my\s+branch|check\s+my\s+branch)\b', clean))
    matched_branch = _match_branch(raw, clean)
    matched_club = _match_club(clean)
    has_club_word = bool(re.search(r'\b(?:\w*clubs?|societ(?:y|ies))\w*\b', clean))
    has_dept_kw = any(re.search(dk, clean) for dk in DEPT_KEYWORDS)

    # Pure Branch-Aware Club Queries (Deterministic Knowledge Path)
    # e.g., "Which clubs are available for my branch?", "Which clubs can I join?", "What clubs are available for ME?"
    is_rec_club_query = bool(re.search(
        r'\b(?:which|what)\s+clubs?\s+(?:are\s+available|can\s+i\s+join|should\s+i\s+join|exist)\b|\bclubs?\s+(?:available\s+for|for)\s+(?:my\s+branch|[a-zA-Z\(\)&-]+)\b|\bwhich\s+clubs\s+can\s+i\s+join\b',
        clean
    ))
    if is_rec_club_query and not (has_dept_kw or has_academic_topic or matched_club):
        cat = None
        for c_cand in ["technical", "cultural", "literary", "outreach", "welfare"]:
            if c_cand in clean:
                cat = c_cand.capitalize()
                break
        return IntentResult(type="recommended_clubs", raw=raw, branch=matched_branch, category=cat)

    # 1. Profile reference + Department/Club/Academic
    if has_profile_ref and (has_dept_kw or matched_club or has_club_word or has_academic_topic):
        return IntentResult(type="agentic", raw=raw)

    # 2. Profile context statement combined with a question
    if has_question_word and (has_academic_topic or is_mem_up) and not is_explicit_up and (extracted_prof or is_mem_up):
        return IntentResult(type="agentic", raw=raw)

    # 3. Department + Club in same query (e.g. "Who is HOD of CSE and what does CodeRIT do?")
    if (matched_branch or has_dept_kw) and (matched_club or (has_club_word and has_question_word)):
        return IntentResult(type="agentic", raw=raw)

    # General profile statements (e.g. "I am in 3rd semester", "My CGPA is 8.97", "Branch: CSE, Semester: 3")
    if (is_mem_up or (invalid_fields and is_mem_up) or (extracted_prof and len(extracted_prof) >= 2)) and not (has_dept_kw and not is_mem_up):
        return IntentResult(type="memory_update", raw=raw, profile_data=extracted_prof, invalid_fields=invalid_fields)

    # 4. Greeting
    for gp in GREETING_PATTERNS:
        if re.search(gp, clean):
            words = clean.split()
            # Ensure it is a short conversational message and not followed by a dept query
            if len(words) <= 4 or not any(re.search(dk, clean) for dk in DEPT_KEYWORDS):
                return IntentResult(type="greeting", raw=raw)

    # 3. Faculty Lookup (specific named faculty members like 'Dr. Siddesh G. M.')
    matched_faculty = lookup_faculty(raw)
    if matched_faculty:
        return IntentResult(type="faculty", entity=matched_faculty["canonical_name"], data=matched_faculty)

    has_faculty = any(re.search(fp, clean) for fp in FACULTY_PATTERNS)
    has_dept_kw = any(re.search(dk, clean) for dk in DEPT_KEYWORDS)
    matched_branch = _match_branch(raw, clean)
    matched_club = _match_club(clean)
    has_club_word = bool(re.search(r'\b(?:\w*clubs?|societ(?:y|ies))\w*\b', clean))

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

    # 5. Knowledge Layer: Recommended Clubs Query
    # e.g. "Which clubs are available for my branch?", "Which clubs can I join?", "What clubs are available for ME?"
    is_rec_club_query = bool(re.search(
        r'\b(?:which|what)\s+clubs?\s+(?:are\s+available|can\s+i\s+join|should\s+i\s+join|exist)\b|\bclubs?\s+(?:available\s+for|for)\s+(?:my\s+branch|[a-zA-Z\(\)&-]+)\b|\bwhich\s+clubs\s+can\s+i\s+join\b',
        clean
    ))
    if is_rec_club_query and not matched_club:
        cat = None
        for c_cand in ["technical", "cultural", "literary", "outreach", "welfare"]:
            if c_cand in clean:
                cat = c_cand.capitalize()
                break
        return IntentResult(type="recommended_clubs", raw=raw, branch=matched_branch, category=cat)

    # 5b. Club Lookup
    # Specific named club queries (e.g. 'CodeRIT', 'What is CodeRIT?', 'SecuRIT', 'Tensor AI', 'TNT')
    if matched_club and not (matched_branch and has_dept_kw):
        return IntentResult(type="club", entity=matched_club)
    if has_club_word and not matched_branch:
        return IntentResult(type="club", entity=None)

    # 5c. Knowledge Layer: Academic Subjects & Curriculum Queries
    # e.g., "What subjects belong to my current semester?", "What subjects do I have?", "What should I study in my semester?"
    is_subject_query = bool(re.search(
        r'\b(?:what\s+(?:are\s+(?:my\s+)?subjects|subjects\s+(?:belong|do\s+i\s+have|are\s+there))|which\s+subjects|show\s+(?:my\s+)?subjects|list\s+(?:my\s+)?subjects|subjects\s+(?:in|for|belonging\s+to)\s+(?:my\s+)?(?:current\s+)?sem(?:ester)?|what\s+should\s+i\s+study\s+in\s+my\s+sem(?:ester)?|what\s+courses\s+do\s+i\s+have)\b',
        clean
    ))
    if is_subject_query:
        cyc = None
        if "physic" in clean:
            cyc = "Physics Cycle"
        elif "chem" in clean:
            cyc = "Chemistry Cycle"
        return IntentResult(type="academic_context", raw=raw, branch=matched_branch, cycle=cyc)

    # 5d. Knowledge Layer: Subject Resources Query
    # e.g., "What academic resources are associated with Programming in C?", "What academic resources are associated with this subject?"
    m_res = re.search(
        r'\b(?:what|which)\s+(?:academic\s+)?resources?\s+(?:are\s+)?(?:associated\s+with|available\s+for|do\s+you\s+have\s+for)\s+(?:this\s+subject\s+)?([a-zA-Z\s\(\)&+-]+)\b',
        clean
    )
    if m_res and not any(re.search(p, clean) for p in DOCUMENT_REQUEST_KEYWORDS):
        cand_subj = m_res.group(1).strip()
        from backend.documents import normalize_subject
        resolved_subj = normalize_subject(cand_subj) or cand_subj.title()
        return IntentResult(type="subject_resources", raw=raw, subject=resolved_subj)

    # 6. Mixed Academic + Document Request
    # Combined requests like "Give me Maths Unit 1 PDF and explain Laplace Transform"
    if re.search(r'\b(?:and|also)\b', clean):
        parts = re.split(r'\b(?:and|also)\b', clean, maxsplit=1)
        part1, part2 = parts[0].strip(), parts[1].strip()
        p1_doc = any(re.search(p, part1) for p in DOCUMENT_REQUEST_KEYWORDS)
        p1_exp = any(re.search(p, part1) for p in ACADEMIC_EXPLANATION_KEYWORDS)
        p2_doc = any(re.search(p, part2) for p in DOCUMENT_REQUEST_KEYWORDS)
        p2_exp = any(re.search(p, part2) for p in ACADEMIC_EXPLANATION_KEYWORDS)

        if (p1_doc and p2_exp) or (p2_doc and p1_exp):
            raw_parts = re.split(r'\b(?:and|also)\b', raw, flags=re.I, maxsplit=1)
            raw_doc_q = raw_parts[0].strip() if p1_doc else raw_parts[1].strip()
            raw_acad_q = raw_parts[1].strip() if p1_doc else raw_parts[0].strip()
            return IntentResult(type="mixed_academic_document", raw=raw, doc_query=raw_doc_q, academic_query=raw_acad_q)

    # 7. Document Retrieval
    is_doc_req = any(re.search(p, clean) for p in DOCUMENT_REQUEST_KEYWORDS)
    is_acad_exp = any(re.search(p, clean) for p in ACADEMIC_EXPLANATION_KEYWORDS)
    has_file_kw = bool(re.search(r'\b(?:give\s+me|download|find|show\s+me|pdf|file|manual|qp|question\s+paper)\b', clean))

    # Academic explanation priority for queries like "Explain this topic from my notes"
    if is_acad_exp and not has_file_kw:
        return IntentResult(type="academic", raw=raw)

    if is_doc_req:
        return IntentResult(type="document_retrieval", raw=raw)

    # 8. Academic Summarize
    if re.search(r'\b(?:summarize|summary\s+of)\b', clean):
        return IntentResult(type="summarize", raw=raw)

    # 9. Academic RAG QA
    has_academic_explicit = any(re.search(ae, clean) for ae in ACADEMIC_EXPLICIT_TERMS)
    has_academic_action = any(re.search(aa, clean) for aa in ACADEMIC_ACTION_TERMS)
    if is_acad_exp or has_academic_explicit or has_academic_action:
        return IntentResult(type="academic", raw=raw)

    # Pure branch name / alias queries (e.g. 'Mechanical', 'CSE', 'Biotechnology', 'Mechanical Engineering')
    if matched_branch:
        q_type = detect_department_query_type(raw)
        return IntentResult(type="department", entity=matched_branch, query_type=q_type)

    # 7. Unknown / Unsupported
    if has_faculty:
        return IntentResult(type="faculty_unknown", raw=raw)

    return IntentResult(type="unknown", raw=raw)


async def handle_message(message: str, student_id: str, force_agentic: bool = False) -> Dict[str, Any]:
    """
    Main message dispatcher.
    Classifies intent deterministically before calling RAG or audited tools.
    Supports controlled agentic execution when multi-domain or explicitly requested.
    """
    t_start = time.perf_counter()
    clean_msg = message.strip() if message else ""
    clean_id = student_id.strip() if student_id else "anonymous"

    if not clean_msg:
        reply = "Please enter a message or question. I can help with MSRIT departments, clubs, academic notes, and your student profile."
        log_action(
            tool_name="empty_input",
            student_id=clean_id,
            parameters={"query": message},
            result_summary="Handled empty or whitespace-only input",
            success=True
        )
        return {
            "answer": reply,
            "action_taken": "empty_input",
            "sources": [],
            "metrics": {
                "router_ms": 0.0,
                "agent_selection_ms": 0.0,
                "tool_execution_ms": 0.0,
                "synthesis_ms": 0.0,
                "total_ms": 0.0,
                "tool_call_count": 0,
                "qwen_call_count": 0,
                "router_time_ms": 0.0,
                "tool_selection_time_ms": 0.0,
                "mcp_tool_time_ms": 0.0,
                "final_answer_time_ms": 0.0,
                "total_time_ms": 0.0
            }
        }

    if force_agentic:
        res = await run_agentic_workflow(clean_msg, clean_id, router_ms=0.0)
        return res

    t_router_start = time.perf_counter()
    intent = classify_intent(clean_msg)
    intent_type = intent["type"]
    router_time_ms = round((time.perf_counter() - t_router_start) * 1000, 2)

    def _with_metrics(
        res_dict: Dict[str, Any],
        tool_time_ms: float = 0.0,
        final_answer_ms: float = 0.0,
        tool_count: int = 0,
        qwen_count: int = 0,
        agent_selection_ms: float = 0.0
    ) -> Dict[str, Any]:
        tot_ms = round((time.perf_counter() - t_start) * 1000, 2)
        res_dict["metrics"] = {
            "router_ms": router_time_ms,
            "agent_selection_ms": round(agent_selection_ms, 2),
            "tool_execution_ms": round(tool_time_ms, 2),
            "synthesis_ms": round(final_answer_ms, 2),
            "total_ms": tot_ms,
            "tool_call_count": tool_count,
            "qwen_call_count": qwen_count,
            # Backward-compatible aliases
            "router_time_ms": router_time_ms,
            "tool_selection_time_ms": round(agent_selection_ms, 2),
            "mcp_tool_time_ms": round(tool_time_ms, 2),
            "final_answer_time_ms": round(final_answer_ms, 2),
            "total_time_ms": tot_ms,
        }
        return res_dict

    # Controlled Agentic Path for Multi-Domain / Combined Queries
    if intent_type == "agentic":
        res = await run_agentic_workflow(clean_msg, clean_id, router_ms=router_time_ms)
        return res

    # 1. IDENTITY / CONVERSATION
    if intent_type == "identity":
        reply = "I'm MSRIT AI, a local-first academic assistant for MSRIT. I can help with MSRIT departments, clubs, academic notes, and your student profile."
        log_action(
            tool_name="conversation",
            student_id=clean_id,
            parameters={"query": clean_msg},
            result_summary="Handled identity question without DB/RAG",
            success=True
        )
        return _with_metrics({
            "answer": reply,
            "action_taken": "conversation",
            "sources": []
        })

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
        return _with_metrics({
            "answer": reply,
            "action_taken": "conversation",
            "sources": []
        })

    # 2. PREFERENCE CLEAR
    if intent_type == "preference_clear":
        t_mcp0 = time.perf_counter()
        res = await mcp_client.call_tool(
            "update_student_profile",
            student_id=clean_id,
            preferences={}
        )
        mcp_time = (time.perf_counter() - t_mcp0) * 1000
        if isinstance(res, dict) and res.get("error"):
            answer = f"Could not clear preferences: {res.get('error')}"
        else:
            answer = "Your saved preferences have been cleared. All other profile details remain unchanged."

        log_action(
            tool_name="update_student_profile",
            student_id=clean_id,
            parameters={"query": clean_msg, "action": "clear_preferences"},
            result_summary="Cleared student preferences",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "update_student_profile",
            "sources": []
        }, tool_time_ms=mcp_time, tool_count=1)

    # 2. MEMORY UPDATE
    if intent_type == "memory_update":
        t_tool0 = time.perf_counter()
        extracted_profile = intent.get("profile_data")
        invalid_fields = intent.get("invalid_fields", [])
        if extracted_profile is None and not invalid_fields:
            extracted_profile, invalid_fields = _extract_profile_data(clean_msg)
        if not extracted_profile:
            extracted_profile = {}

        if invalid_fields:
            if "cgpa" in invalid_fields:
                answer = "Please provide a valid numeric CGPA between 0.0 and 10.0 (e.g., 8.97)."
            elif "semester" in invalid_fields:
                answer = "Please provide a valid semester number between 1 and 10."
            elif "year" in invalid_fields:
                answer = "Please provide a valid academic year between 1 and 6."
            elif "explanation_style" in invalid_fields:
                answer = "Invalid explanation style. Supported styles are 'concise' (short/brief/direct) or 'detailed' (long/thorough/in-depth)."
            elif "focus_subject" in invalid_fields:
                from backend.memory import SUPPORTED_FIRST_YEAR_SUBJECTS
                answer = f"Invalid focus subject. Supported first-year subjects are: {', '.join(sorted(SUPPORTED_FIRST_YEAR_SUBJECTS))}."
            else:
                answer = f"I could not understand the value provided for {', '.join(invalid_fields)}. Please provide a valid value."

            log_action(
                tool_name="update_student_profile",
                student_id=clean_id,
                parameters={"query": clean_msg, "invalid_fields": invalid_fields},
                result_summary="Profile update rejected due to invalid values",
                success=False
            )
            return _with_metrics({
                "answer": answer,
                "action_taken": "update_student_profile",
                "sources": []
            })

        mcp_time = 0.0
        tool_cnt = 0
        if extracted_profile:
            t_mcp0 = time.perf_counter()
            res = await mcp_client.call_tool(
                "update_student_profile",
                student_id=clean_id,
                **extracted_profile
            )
            mcp_time = (time.perf_counter() - t_mcp0) * 1000
            tool_cnt = 1
            if isinstance(res, dict) and res.get("error"):
                answer = f"Could not update profile: {res.get('error')}"
            else:
                field_labels = [
                    ("name", "Name"),
                    ("college", "College"),
                    ("degree", "Degree"),
                    ("branch", "Branch"),
                    ("semester", "Semester"),
                    ("year", "Year"),
                    ("cgpa", "CGPA"),
                    ("stream", "Stream"),
                    ("cycle", "Cycle")
                ]
                lines = [f"Profile updated successfully for {clean_id}:"]
                for key, label in field_labels:
                    if key in extracted_profile:
                        lines.append(f"- **{label}:** {extracted_profile[key]}")
                if "preferences" in extracted_profile and isinstance(extracted_profile["preferences"], dict):
                    prefs = extracted_profile["preferences"]
                    if "explanation_style" in prefs:
                        lines.append(f"- **Explanation Style:** {prefs['explanation_style']}")
                    if "focus_subject" in prefs:
                        lines.append(f"- **Focus Subject:** {prefs['focus_subject']}")
                answer = "\n".join(lines)
        else:
            answer = "What profile information would you like to update? You can specify details like Branch: CSE, Semester: 3, Name: Vishal, CGPA: 8.97, etc."

        log_action(
            tool_name="update_student_profile",
            student_id=clean_id,
            parameters={"query": clean_msg, **(extracted_profile or {})},
            result_summary="Updated student profile",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "update_student_profile",
            "sources": []
        }, tool_time_ms=mcp_time, tool_count=tool_cnt)

    # 3. MEMORY QUERY
    if intent_type == "memory_query":
        q_field = intent.get("query_field") or detect_profile_query_field(clean_msg)
        t_mcp0 = time.perf_counter()
        res = await mcp_client.call_tool("get_student_profile", student_id=clean_id)
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

        if isinstance(res, dict) and "error" in res:
            answer = "MSRIT knowledge service is temporarily unavailable. Please check that the local database and MCP service are running."
        elif not res or not any(res.get(k) is not None for k in ["name", "college", "degree", "branch", "semester", "year", "stream", "cycle", "cgpa", "preferences"]):
            if q_field in ("preferences", "explanation_style", "focus_subject"):
                answer = "You don't have any saved preferences yet."
            else:
                answer = "You haven't set your profile yet. You can tell me something like 'My name is Vishal and I am in 3rd semester CSE' to set it up!"
        else:
            if q_field != "full":
                answer = format_single_field_response(res, q_field)
            else:
                answer = format_profile_overview(res, clean_id)

        log_action(
            tool_name="get_student_profile",
            student_id=clean_id,
            parameters={"query": clean_msg, "field": q_field},
            result_summary="Retrieved student profile",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "get_student_profile",
            "sources": []
        }, tool_time_ms=mcp_time, tool_count=1)

    # 3. DEPARTMENT LOOKUP
    if intent_type == "department":
        target = intent.get("entity") or clean_msg
        query_type = intent.get("query_type") or detect_department_query_type(clean_msg)
        t_mcp0 = time.perf_counter()
        res = await mcp_client.call_tool("lookup_department", query=target)
        if isinstance(res, dict) and "error" in res and "Unknown tool" in res.get("error", ""):
            res = await mcp_client.call_tool("lookup_branch", query=target)
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

        final_ans_time = 0.0
        # 1. SERVICE ERROR (MCP, transport, or process failure)
        if isinstance(res, dict) and "error" in res:
            answer = "MSRIT knowledge service is temporarily unavailable. Please check that the local database and MCP service are running."
        # 2. SUCCESS (lookup succeeded and branch record found)
        elif isinstance(res, dict) and res.get("code"):
            t_g0 = time.perf_counter()
            answer = await generate_grounded_response(clean_msg, res, query_type)
            final_ans_time = (time.perf_counter() - t_g0) * 1000
        # 3. NOT FOUND (lookup executed but no department matched)
        else:
            answer = f"No department details found matching '{target}'. Please specify a recognized branch name or code (e.g., CSE, ME, Civil, ECE)."

        qwen_cnt = 1 if final_ans_time > 0 else 0
        return _with_metrics({
            "answer": answer,
            "action_taken": "lookup_branch",
            "sources": []
        }, tool_time_ms=mcp_time, final_answer_ms=final_ans_time, tool_count=1, qwen_count=qwen_cnt)

    # 4. CLUB LOOKUP
    if intent_type == "club":
        target = intent.get("entity")
        category = None
        low = clean_msg.lower()
        if "technical" in low:
            category = "Technical"
        elif "cultural" in low:
            category = "Cultural"

        query_param = target
        if not query_param:
            cleaned_q = re.sub(r'\b(?:clubs?|societ(?:y|ies)|tell\s+me\s+about|what\s+is|what\s+are|list|show|what|are|available|all|any|can\s+you\s+list)\b', '', low)
            cleaned_q = re.sub(r'[^\w\s]', ' ', cleaned_q).strip()
            query_param = cleaned_q if cleaned_q else None

        t_mcp0 = time.perf_counter()
        res = await mcp_client.call_tool("lookup_club", query=query_param, category=category)
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

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

        return _with_metrics({
            "answer": answer,
            "action_taken": "lookup_club",
            "sources": []
        }, tool_time_ms=mcp_time, tool_count=1)

    # 5. MIXED ACADEMIC + DOCUMENT RETRIEVAL
    if intent_type == "mixed_academic_document":
        doc_q = intent.get("doc_query") or clean_msg
        acad_q = intent.get("academic_query") or clean_msg

        # A. Retrieve document
        doc_params = detect_document_query_params(doc_q)
        t_mcp0 = time.perf_counter()
        doc_res = await mcp_client.call_tool(
            "search_academic_documents",
            subject=doc_params.get("subject"),
            unit=doc_params.get("unit"),
            document_type=doc_params.get("document_type"),
            year=doc_params.get("year"),
            query=doc_params.get("title_keyword")
        )
        mcp_time = (time.perf_counter() - t_mcp0) * 1000
        if isinstance(doc_res, dict) and "error" in doc_res:
            docs = search_academic_documents(
                subject=doc_params.get("subject"),
                unit=doc_params.get("unit"),
                document_type=doc_params.get("document_type"),
                year=doc_params.get("year"),
                query=doc_params.get("title_keyword")
            )
        else:
            docs = doc_res if isinstance(doc_res, list) else ([doc_res] if isinstance(doc_res, dict) and "title" in doc_res else [])

        doc_answer, doc_sources = format_document_response(docs, doc_params)

        # B. Academic explanation via local RAG
        t_rag0 = time.perf_counter()
        acad_res = await asyncio.to_thread(rag.answer_question, query=acad_q, student_id=clean_id)
        rag_time = (time.perf_counter() - t_rag0) * 1000
        acad_answer = acad_res.get("answer", "")
        acad_sources = acad_res.get("sources", [])

        combined_answer = f"{doc_answer}\n\n---\n**Academic Explanation:**\n{acad_answer}"
        combined_sources = doc_sources + [s for s in acad_sources if s not in doc_sources]

        log_action(
            tool_name="mixed_document_and_academic",
            student_id=clean_id,
            parameters={"doc_query": doc_q, "academic_query": acad_q},
            result_summary=f"Found {len(docs)} doc(s), explained academic query",
            success=True
        )
        return _with_metrics({
            "answer": combined_answer,
            "action_taken": "mixed_document_and_academic",
            "sources": combined_sources
        }, tool_time_ms=mcp_time, final_answer_ms=rag_time, tool_count=1, qwen_count=1)

    # 6. DOCUMENT RETRIEVAL
    if intent_type == "document_retrieval":
        params = detect_document_query_params(clean_msg)

        # Ambiguity Case A: User specifies unit without specifying subject
        if params.get("needs_subject_clarification"):
            unit_val = params.get("unit")
            unit_str = f"Unit {unit_val}" if unit_val is not None else "that unit"
            answer = f"Which subject's {unit_str} do you want? (e.g., Mathematics, Physics, Chemistry, C Programming)"
            log_action(
                tool_name="search_academic_documents",
                student_id=clean_id,
                parameters={"query": clean_msg, **params},
                result_summary="Requested clarification for missing subject",
                success=True
            )
            return _with_metrics({
                "answer": answer,
                "action_taken": "search_academic_documents",
                "sources": []
            })

        # Ambiguity Case B: Generic query like "Give me the maths PDF" without unit or specific doc_type
        if params.get("needs_type_clarification"):
            subj_val = params.get("subject") or "course"
            answer = f"Sure. Do you want {subj_val} notes, a question paper, lab manual, or the syllabus?"
            log_action(
                tool_name="search_academic_documents",
                student_id=clean_id,
                parameters={"query": clean_msg, **params},
                result_summary="Requested clarification for generic document type",
                success=True
            )
            return _with_metrics({
                "answer": answer,
                "action_taken": "search_academic_documents",
                "sources": []
            })

        t_mcp0 = time.perf_counter()
        res = await mcp_client.call_tool(
            "search_academic_documents",
            subject=params.get("subject"),
            unit=params.get("unit"),
            document_type=params.get("document_type"),
            year=params.get("year"),
            query=params.get("title_keyword")
        )
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

        if isinstance(res, dict) and "error" in res:
            docs = search_academic_documents(
                subject=params.get("subject"),
                unit=params.get("unit"),
                document_type=params.get("document_type"),
                year=params.get("year"),
                query=params.get("title_keyword")
            )
        else:
            docs = res if isinstance(res, list) else ([res] if isinstance(res, dict) and "title" in res else [])

        answer, sources = format_document_response(docs, params)

        log_action(
            tool_name="search_academic_documents",
            student_id=clean_id,
            parameters={"query": clean_msg, **params},
            result_summary=f"Found {len(docs)} document(s)",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "search_academic_documents",
            "sources": sources
        }, tool_time_ms=mcp_time, tool_count=1)

    # 6b. KNOWLEDGE LAYER: ACADEMIC CONTEXT / SUBJECTS
    if intent_type == "academic_context":
        t_mcp0 = time.perf_counter()
        target_branch = intent.get("branch")
        target_cycle = intent.get("cycle")
        res = await mcp_client.call_tool(
            "get_academic_context",
            student_id=clean_id,
            branch=target_branch,
            cycle=target_cycle
        )
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

        if isinstance(res, dict) and res.get("error"):
            answer = f"Could not retrieve academic curriculum: {res.get('error')}"
        elif isinstance(res, dict):
            answer = format_academic_context_response(res)
        else:
            answer = "Unable to retrieve academic curriculum at this time."

        log_action(
            tool_name="get_academic_context",
            student_id=clean_id,
            parameters={"query": clean_msg, "branch": target_branch, "cycle": target_cycle},
            result_summary=f"Resolved academic context for {target_branch or clean_id}",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "get_academic_context",
            "sources": []
        }, tool_time_ms=mcp_time, tool_count=1)

    # 6c. KNOWLEDGE LAYER: RECOMMENDED CLUBS FOR BRANCH
    if intent_type == "recommended_clubs":
        t_mcp0 = time.perf_counter()
        target_branch = intent.get("branch")
        target_cat = intent.get("category")

        # If branch not specified in query, check student profile
        if not target_branch and clean_id != "anonymous":
            prof = await mcp_client.call_tool("get_student_profile", student_id=clean_id)
            if isinstance(prof, dict) and prof.get("branch"):
                target_branch = prof.get("branch")

        res = await mcp_client.call_tool(
            "get_recommended_clubs",
            branch=target_branch,
            category=target_cat
        )
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

        clubs_list = res if isinstance(res, list) else []
        answer = format_recommended_clubs_response(clubs_list, branch=target_branch)

        log_action(
            tool_name="get_recommended_clubs",
            student_id=clean_id,
            parameters={"query": clean_msg, "branch": target_branch, "category": target_cat},
            result_summary=f"Found {len(clubs_list)} recommended clubs for {target_branch or 'all'}",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "get_recommended_clubs",
            "sources": []
        }, tool_time_ms=mcp_time, tool_count=1)

    # 6d. KNOWLEDGE LAYER: SUBJECT RESOURCES
    if intent_type == "subject_resources":
        subj = intent.get("subject")
        if not subj and clean_id != "anonymous":
            prof = await mcp_client.call_tool("get_student_profile", student_id=clean_id)
            if isinstance(prof, dict):
                prefs = prof.get("preferences") or {}
                if isinstance(prefs, dict) and prefs.get("focus_subject"):
                    subj = prefs["focus_subject"]
        t_mcp0 = time.perf_counter()
        docs = await mcp_client.call_tool(
            "search_academic_documents",
            subject=subj,
            limit=10
        )
        mcp_time = (time.perf_counter() - t_mcp0) * 1000

        doc_list = docs if isinstance(docs, list) else []
        answer, sources = format_document_response(doc_list, {"subject": subj})

        log_action(
            tool_name="search_academic_documents",
            student_id=clean_id,
            parameters={"query": clean_msg, "subject": subj},
            result_summary=f"Found {len(doc_list)} resources for {subj}",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "search_academic_documents",
            "sources": sources
        }, tool_time_ms=mcp_time, tool_count=1)

    # 7. ACADEMIC SUMMARIZE
    if intent_type == "summarize":
        subject = _extract_subject_for_summary(clean_msg)
        if subject:
            t_rag0 = time.perf_counter()
            res = await asyncio.to_thread(rag.summarize_notes, subject=subject)
            rag_time = (time.perf_counter() - t_rag0) * 1000
            return _with_metrics({
                "answer": res.get("summary", "No summary generated."),
                "action_taken": "summarize_notes",
                "sources": res.get("sources", [])
            }, final_answer_ms=rag_time, tool_count=1, qwen_count=1)

    # 8. ACADEMIC RAG QA
    if intent_type == "academic":
        t_rag0 = time.perf_counter()
        res = await asyncio.to_thread(rag.answer_question, query=clean_msg, student_id=clean_id)
        rag_time = (time.perf_counter() - t_rag0) * 1000
        return _with_metrics({
            "answer": res.get("answer", "No answer could be generated."),
            "action_taken": "answer_question",
            "sources": res.get("sources", [])
        }, final_answer_ms=rag_time, tool_count=0, qwen_count=1)

    # 9. FACULTY LOOKUP
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
            return _with_metrics({
                "answer": answer,
                "action_taken": "lookup_faculty",
                "sources": []
            }, tool_count=1)

    # 10. FACULTY DIRECTORY PLACEHOLDER
    if intent_type == "faculty_unknown":
        answer = "I don't currently have a faculty directory for that person. I can help with MSRIT departments, clubs, academic notes, or your student profile."
        log_action(
            tool_name="faculty_directory_placeholder",
            student_id=clean_id,
            parameters={"query": clean_msg},
            result_summary="Faculty lookup unsupported - safe placeholder returned",
            success=True
        )
        return _with_metrics({
            "answer": answer,
            "action_taken": "unknown_faculty",
            "sources": []
        })

    # 11. UNKNOWN / UNSUPPORTED
    answer = "I’m not sure what you’re asking about. I can currently help with MSRIT departments, clubs, academic notes, and your student profile."
    log_action(
        tool_name="unknown_clarification",
        student_id=clean_id,
        parameters={"query": clean_msg},
        result_summary="Out-of-scope query - clarification returned without RAG",
        success=True
    )
    return _with_metrics({
        "answer": answer,
        "action_taken": "unknown_clarification",
        "sources": []
    })
