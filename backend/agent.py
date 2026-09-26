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
from backend.documents import (
    detect_document_query_params,
    search_academic_documents,
    format_document_response
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

MEMORY_UPDATE_PATTERNS = [
    r'\b(?:update|change|set|save|record|add)\s+(?:my\s+)?profile\b',
    r'\b(?:my\s+name\s+is|my\s+name\'s)\b',
    r'\b(?:my\s+cgpa\s+is|my\s+gpa\s+is)\b',
    r'\b(?:with\s+cgpa|cgpa\s*[:=]|gpa\s*[:=])\b',
    r'\b(?:my\s+branch\s+is|my\s+branch\s*:)\b',
    r'\b(?:my\s+semester\s+is|my\s+sem\s+is)\b',
    r'\b(?:my\s+college\s+is|my\s+degree\s+is|my\s+stream\s+is|my\s+cycle\s+is)\b',
    r'\b(?:i\s+am\s+studying|i\'m\s+studying|i\s+study\s+at)\b',
    r'\b(?:i\s+am\s+pursuing|i\'m\s+pursuing|currently\s+pursuing)\b',
    r'\b(?:i\s+am\s+in|i\'m\s+in)\b',
    r'\b(?:i\s+am\s+a\s+\d+(?:st|nd|rd|th)?\s+year\s+student|i\s+completed\s+my\s+\d+(?:st|nd|rd|th)?\s+year)\b',
    r'\b(?:remember\s+that\s+i|remember\s+my)\b',
    r'\b(?:branch\s*[:=]|semester\s*[:=]|sem\s*[:=]|stream\s*[:=]|cycle\s*[:=]|cgpa\s*[:=]|college\s*[:=]|degree\s*[:=]|year\s*[:=]|name\s*[:=])\b'
]

MEMORY_QUERY_PATTERNS = [
    r'\b(?:who\s+am\s+i|tell\s+me\s+about\s+myself|what\s+do\s+you\s+know\s+about\s+me|show\s+my\s+profile|what\s+is\s+my\s+profile|^my\s+profile$|^my\s+details$)\b',
    r'\b(?:what\s+is\s+my\s+name|what\s+is\s+my\s+branch|what\s+branch\s+am\s+i\s+in)\b',
    r'\b(?:what\s+semester\s+am\s+i\s+in|which\s+semester\s+am\s+i\s+in|what\s+is\s+my\s+semester|what\s+is\s+my\s+sem)\b',
    r'\b(?:what\s+is\s+my\s+cgpa|what\s+is\s+my\s+gpa|what\s+is\s+my\s+grade|what\s+is\s+my\s+score)\b',
    r'\b(?:which\s+college\s+do\s+i\s+study\s+in|what\s+college\s+do\s+i\s+study\s+in|what\s+is\s+my\s+college|where\s+do\s+i\s+study)\b',
    r'\b(?:what\s+course\s+am\s+i\s+pursuing|what\s+degree\s+am\s+i\s+pursuing|what\s+is\s+my\s+degree|what\s+is\s+my\s+course)\b',
]


def detect_profile_query_field(query: str) -> str:
    """
    Detects which specific profile field a user is querying, or 'full' for overall profile.
    """
    low = query.lower()
    if re.search(r'\b(?:name)\b', low):
        return "name"
    if re.search(r'\b(?:cgpa|gpa|grade|score)\b', low):
        return "cgpa"
    if re.search(r'\b(?:branch)\b', low):
        return "branch"
    if re.search(r'\b(?:sem(?:ester)?)\b', low):
        return "semester"
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
    r'\b(?:maths?|physics|chemistry|c\s+programming|civil|mechanical)\s+(?:notes?|pdf|question\s+papers?|pyqs?|lab\s+manual|syllabus)\b',
    r'\b(?:give\s+me|show\s+me|find|get|download)\s+(?:the\s+)?(?:maths?|physics|chemistry|c\s+programming)\b',
    r'\b(?:give\s+me|show\s+me|find|get)\s+unit\s*[-_]?\s*(?:\d+|i{1,3}|iv|v)\b'
]

ACADEMIC_EXPLANATION_KEYWORDS = [
    r'\b(?:explain|definition\s+of|define|derive|derivation|what\s+is\s+(?:a|an|the)?|what\s+are|teach\s+me|how\s+does.*work|how\s+do|difference\s+between|concept\s+of|algorithm\s+for|sorting\s+algorithms?|recursion|pointers?|linked\s+list|stack\s+and\s+queue)\b',
    r'\b(?:explain\s+unit\s*\d+|explain\s+this\s+concept|explain\s+this\s+topic|explain\s+laplace)\b',
    r'\bexplain\s+laplace\s+transform\b'
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


def _extract_profile_data(message: str) -> Dict[str, Any]:
    """
    Extracts all supported student profile fields from natural language or key-value formatted text:
    name, college, degree, branch, semester, year, stream, cycle, cgpa.
    Only extracts information explicitly provided by the user.
    """
    data = {}
    lower = message.lower()
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', lower).strip()

    # 1. Name
    m_name_kv = re.search(r'\bname\s*[:=]\s*([a-zA-Z\s\.\'-]+?)(?:,|$|\b(?:and|with|branch|sem|semester|cgpa|college|degree|year|stream|cycle)\b)', message, re.I)
    m_name_nat = re.search(r'\bmy\s+name\s+is\s+([a-zA-Z\s\.\'-]+?)(?:,|$|\.|\b(?:and|i\s+am|studying|currently|with|cgpa|branch|sem|semester|at)\b)', message, re.I)
    raw_name = (m_name_kv.group(1) if m_name_kv else (m_name_nat.group(1) if m_name_nat else None))
    if raw_name:
        clean_name = raw_name.strip(' .,;:-')
        if len(clean_name) >= 2 and clean_name.lower() not in {'not specified', 'a', 'an', 'the', 'msrit'}:
            data['name'] = clean_name

    # 2. CGPA
    m_cgpa = re.search(r'\b(?:cgpa|gpa)\s*[:=]?\s*(?:is\s*)?(\d+(?:\.\d+)?)\b', message, re.I)
    if not m_cgpa:
        m_cgpa = re.search(r'\b(?:with\s+)?(\d+(?:\.\d+)?)\s*(?:cgpa|gpa)\b', message, re.I)
    if m_cgpa:
        try:
            val = float(m_cgpa.group(1))
            if 0.0 <= val <= 10.0:
                data['cgpa'] = val
        except ValueError:
            pass

    # 3. Semester
    m_sem_kv = re.search(r'\b(?:semester|sem)\s*[:=]\s*(\d+)\b', message, re.I)
    m_sem_nat = re.search(r'\b(?:in\s+)?(\d+)(?:st|nd|rd|th)?\s*(?:semester|sem)\b', message, re.I)
    m_sem_nat2 = re.search(r'\b(?:semester|sem)\s*(?:is\s*)?(\d+)\b', message, re.I)
    sem_val = (m_sem_kv.group(1) if m_sem_kv else (m_sem_nat.group(1) if m_sem_nat else (m_sem_nat2.group(1) if m_sem_nat2 else None)))
    if sem_val:
        try:
            s_int = int(sem_val)
            if 1 <= s_int <= 10:
                data['semester'] = s_int
        except ValueError:
            pass

    # 4. Year
    m_yr_kv = re.search(r'\byear\s*[:=]\s*(\d+)\b', message, re.I)
    m_yr_dig = re.search(r'\b(?:completed\s+my\s+|in\s+|am\s+in\s+|a\s+)?(\d+)(?:st|nd|rd|th)\s+year\b', message, re.I)
    m_yr_word = re.search(r'\b(?:completed\s+my\s+|in\s+|am\s+in\s+|a\s+)?(first|second|third|fourth)\s+year\b', message, re.I)
    word_map = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
    yr_val = (m_yr_kv.group(1) if m_yr_kv else (m_yr_dig.group(1) if m_yr_dig else None))
    if yr_val:
        try:
            y_int = int(yr_val)
            if 1 <= y_int <= 6:
                data['year'] = y_int
        except ValueError:
            pass
    elif m_yr_word and m_yr_word.group(1).lower() in word_map:
        data['year'] = word_map[m_yr_word.group(1).lower()]

    # 5. College
    m_col_kv = re.search(r'\b(?:college|institution)\s*[:=]\s*([a-zA-Z0-9\s\.\'-]+?)(?:,|$|\b(?:branch|sem|semester|stream|cycle|cgpa|degree|year)\b)', message, re.I)
    m_col_nat = re.search(r'\b(?:studying\s+in|study\s+at|student\s+at|at)\s+(msrit|ramaiah\s+institute\s+of\s+technology|ramaiah)\b', message, re.I)
    if m_col_kv:
        data['college'] = m_col_kv.group(1).strip()
    elif m_col_nat:
        data['college'] = 'MSRIT'

    # 6. Degree
    m_deg_kv = re.search(r'\bdegree\s*[:=]\s*([a-zA-Z\.\s]+?)(?:,|$|\b(?:with|branch|sem|semester|stream|cycle|cgpa|year)\b)', message, re.I)
    m_deg_nat = re.search(r'\b(?:pursuing|doing|studying\s+for|for)\s+(be|b\.e\.|btech|b\.tech|mtech|m\.tech|mca|mba|barch|b\.arch)\b', message, re.I)
    deg_val = m_deg_kv.group(1) if m_deg_kv else (m_deg_nat.group(1) if m_deg_nat else None)
    if deg_val:
        clean_deg = deg_val.strip().upper().replace('.', '')
        data['degree'] = clean_deg

    # 7. Branch
    m_br_kv = re.search(r'\bbranch\s*[:=]\s*([a-zA-Z0-9\(\)&-]+)', message, re.I)
    if m_br_kv:
        code = find_branch_code(m_br_kv.group(1)) or _match_branch(m_br_kv.group(1), m_br_kv.group(1).lower())
        if code:
            data['branch'] = code
        else:
            data['branch'] = m_br_kv.group(1).strip()
    else:
        # Match from natural message
        b_code = _match_branch(message, clean)
        if b_code:
            data['branch'] = b_code

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
    1. Identity / Conversation
    2. Memory Update / Profile Statements
    3. Memory Query (Profile Questions)
    4. Greeting
    5. Faculty Lookup (HOD/Faculty by name)
    6. Department Lookup (field-specific or full)
    7. Club Lookup
    8. Academic RAG / Summarization
    9. Unknown / Faculty directory placeholder
    """
    raw = message.strip()
    low = raw.lower()
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', low).strip()

    # 1. Identity (MSRIT AI assistant identity - never matches student queries like 'who am i')
    for ip in IDENTITY_PATTERNS:
        if re.search(ip, clean):
            return IntentResult(type="identity", raw=raw)

    # 2. Memory Update (Statements providing student profile information)
    is_mem_up = any(re.search(mp, clean) for mp in MEMORY_UPDATE_PATTERNS)
    extracted_prof = _extract_profile_data(raw)
    if is_mem_up or (extracted_prof and len(extracted_prof) >= 2):
        return IntentResult(type="memory_update", raw=raw, profile_data=extracted_prof)

    # 3. Memory Query (Student queries asking about their own profile details)
    for mq in MEMORY_QUERY_PATTERNS:
        if re.search(mq, clean):
            q_field = detect_profile_query_field(clean)
            return IntentResult(type="memory_query", raw=raw, query_field=q_field)

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
        reply = "I'm MSRIT AI, a local-first academic assistant for MSRIT. I can help with MSRIT departments, clubs, academic notes, and your student profile."
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
        extracted_profile = intent.get("profile_data")
        if not extracted_profile:
            extracted_profile = _extract_profile_data(clean_msg)

        if extracted_profile:
            res = await mcp_client.call_tool(
                "update_student_profile",
                student_id=clean_id,
                **extracted_profile
            )
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
                answer = "\n".join(lines)
        else:
            answer = "I couldn't identify any profile details to update. You can specify details like Branch:CSE, Semester:3, Name: Vishal, CGPA: 8.97, etc."

        log_action(
            tool_name="update_student_profile",
            student_id=clean_id,
            parameters={"query": clean_msg, **(extracted_profile or {})},
            result_summary="Updated student profile",
            success=True
        )
        return {
            "answer": answer,
            "action_taken": "update_student_profile",
            "sources": []
        }

    # 3. MEMORY QUERY
    if intent_type == "memory_query":
        q_field = intent.get("query_field") or detect_profile_query_field(clean_msg)
        res = await mcp_client.call_tool("get_student_profile", student_id=clean_id)

        if isinstance(res, dict) and "error" in res:
            answer = "MSRIT knowledge service is temporarily unavailable. Please check that the local database and MCP service are running."
        elif not res or not any(res.get(k) is not None for k in ["name", "college", "degree", "branch", "semester", "year", "stream", "cycle", "cgpa"]):
            answer = "You haven't set your profile yet. You can tell me something like 'My name is Vishal and I am in 3rd semester CSE' to set it up!"
        else:
            if q_field == "name":
                answer = f"Your name is {res['name']}." if res.get("name") else "I don't have your name in your profile yet."
            elif q_field == "cgpa":
                answer = f"Your CGPA is {res['cgpa']}." if res.get("cgpa") is not None else "I don't have your CGPA recorded in your profile yet."
            elif q_field == "branch":
                answer = f"You are in the {res['branch']} branch." if res.get("branch") else "I don't have your branch recorded in your profile yet."
            elif q_field == "semester":
                answer = f"You are currently in semester {res['semester']}." if res.get("semester") is not None else "I don't have your semester recorded in your profile yet."
            elif q_field == "college":
                answer = f"You study at {res['college']}." if res.get("college") else "I don't have your college recorded in your profile yet."
            elif q_field == "degree":
                if res.get("degree") and res.get("branch"):
                    answer = f"You are pursuing {res['degree']} in {res['branch']}."
                elif res.get("degree"):
                    answer = f"You are pursuing {res['degree']}."
                elif res.get("branch"):
                    answer = f"You are in the {res['branch']} branch."
                else:
                    answer = "I don't have your degree or course recorded in your profile yet."
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
                lines = [f"**Your Student Profile ({clean_id}):**"]
                for key, label in field_labels:
                    val = res.get(key)
                    if val is not None and str(val).strip():
                        lines.append(f"- **{label}:** {val}")
                answer = "\n".join(lines)

        log_action(
            tool_name="get_student_profile",
            student_id=clean_id,
            parameters={"query": clean_msg, "field": q_field},
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
            answer = await generate_grounded_response(clean_msg, res, query_type)
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

    # 5. MIXED ACADEMIC + DOCUMENT RETRIEVAL
    if intent_type == "mixed_academic_document":
        doc_q = intent.get("doc_query") or clean_msg
        acad_q = intent.get("academic_query") or clean_msg

        # A. Retrieve document
        doc_params = detect_document_query_params(doc_q)
        doc_res = await mcp_client.call_tool(
            "search_academic_documents",
            subject=doc_params.get("subject"),
            unit=doc_params.get("unit"),
            document_type=doc_params.get("document_type"),
            year=doc_params.get("year"),
            query=doc_params.get("title_keyword")
        )
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
        acad_res = await asyncio.to_thread(rag.answer_question, query=acad_q, student_id=clean_id)
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
        return {
            "answer": combined_answer,
            "action_taken": "mixed_document_and_academic",
            "sources": combined_sources
        }

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
            return {
                "answer": answer,
                "action_taken": "search_academic_documents",
                "sources": []
            }

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
            return {
                "answer": answer,
                "action_taken": "search_academic_documents",
                "sources": []
            }

        res = await mcp_client.call_tool(
            "search_academic_documents",
            subject=params.get("subject"),
            unit=params.get("unit"),
            document_type=params.get("document_type"),
            year=params.get("year"),
            query=params.get("title_keyword")
        )

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
        return {
            "answer": answer,
            "action_taken": "search_academic_documents",
            "sources": sources
        }

    # 7. ACADEMIC SUMMARIZE
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
