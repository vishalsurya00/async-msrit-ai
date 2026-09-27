"""
Conversation Context and Multi-Turn Follow-up Resolver for RIT NEXUS.
Maintains lightweight, session-aware context for:
1. Academic document candidate selection (e.g. "laser", "2023 May", "the first one", "Cprog")
2. Entity and pronoun follow-ups (e.g. "Who is the HOD of CSE?" -> "Where is his department?")
3. Explanation continuations (e.g. "Explain corrosion mechanism" -> "What happens at the cathode?" / "Explain it simply")
4. Stale-context protection and document path privacy.
"""
from typing import Optional, Dict, Any, List, Tuple
import re
import time
import sys

PUBLIC_FIRST_YEAR_URL = "https://ritnotebook.pages.dev/notes/first"
CONTEXT_EXPIRY_SECONDS = 900  # 15 minutes of inactivity before context is considered stale

# Unified in-memory session context storage, keyed by session_id or student_id
_SESSION_CONTEXTS: Dict[str, Dict[str, Any]] = {}
_PENDING_ACADEMIC_CONTEXTS: Dict[str, Dict[str, Any]] = {}


def get_session_context(key: str) -> Dict[str, Any]:
    """Retrieve session context dict. Cleans up stale context automatically."""
    if not key:
        return {}
    ctx = _SESSION_CONTEXTS.get(key)
    if not ctx:
        return {}
    # Staleness check
    last_updated = ctx.get("last_updated", 0)
    if time.time() - last_updated > CONTEXT_EXPIRY_SECONDS:
        _SESSION_CONTEXTS.pop(key, None)
        return {}
    return ctx


def set_session_context(key: str, context: Dict[str, Any]) -> None:
    """Store session context with current timestamp."""
    if not key:
        return
    context["last_updated"] = time.time()
    _SESSION_CONTEXTS[key] = context


def clear_session_context(key: str) -> None:
    """Clear session context."""
    if key:
        _SESSION_CONTEXTS.pop(key, None)


# Backward-compatible helpers for Step 7 tests and MCP tools
def get_academic_context(student_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve temporary pending academic context for a student session."""
    ctx = get_session_context(student_id)
    if ctx and ctx.get("pending_academic"):
        return ctx["pending_academic"]
    return _PENDING_ACADEMIC_CONTEXTS.get(student_id)


def set_academic_context(student_id: str, context: Dict[str, Any]) -> None:
    """Store temporary pending academic context for a student session."""
    _PENDING_ACADEMIC_CONTEXTS[student_id] = context
    ctx = get_session_context(student_id)
    ctx["pending_academic"] = context
    set_session_context(student_id, ctx)


def clear_academic_context(student_id: str) -> None:
    """Clear temporary pending academic context for a student session."""
    _PENDING_ACADEMIC_CONTEXTS.pop(student_id, None)
    ctx = get_session_context(student_id)
    if ctx:
        ctx.pop("pending_academic", None)


def _clean_text(text: str) -> str:
    """Lowercase and strip non-alphanumeric punctuation except common separators."""
    low = text.lower().strip()
    return re.sub(r'[^\w\s\(\)&+-]', ' ', low).strip()


def _tokenize(text: str) -> List[str]:
    """Tokenize into meaningful words and stems."""
    clean = _clean_text(text)
    stopwords = {
        "the", "a", "an", "one", "notes", "note", "pdf", "file", "document",
        "documents", "question", "questions", "paper", "papers", "ppr", "pyq",
        "pyqs", "please", "give", "me", "show", "i", "am", "want", "for", "and", "or",
        "of", "in", "to", "is", "about", "with", "what", "which", "where", "who",
        "my", "your", "you", "do", "does", "have", "has", "find"
    }
    raw_tokens = [w for w in re.split(r'[\s_]+', clean) if w]
    tokens = []
    for t in raw_tokens:
        if t in stopwords and len(t) <= 3:
            continue
        tokens.append(t)
        # Normalize simple plurals
        if t.endswith("s") and len(t) > 3 and not t.endswith("ss"):
            tokens.append(t[:-1])
        # Stem 'fibres'/'fibers'
        if t in ("fibres", "fibers", "fibre", "fiber"):
            tokens.extend(["fibre", "fiber", "fibres", "fibers"])
        # Stem 'sept'/'september'
        if t in ("sept", "september"):
            tokens.extend(["sept", "september"])
    return list(dict.fromkeys(tokens))


def format_resolved_document_response(doc: Dict[str, Any], subject: str, doc_type: str = "notes") -> str:
    """
    Format a clean user-facing response for an unambiguously resolved document.
    Never exposes internal filesystem paths or data/raw directories.
    Provides the public first-year resource link.
    """
    title = (doc.get("title") or "").strip()
    unit = doc.get("unit")
    unit_str = f" Unit {unit}" if unit is not None else ""
    dt = doc.get("document_type") or doc_type

    if dt == "question_paper":
        clean_title = title
        if clean_title.lower() == "2023 may":
            clean_title = "2023 May"
        elif clean_title.lower() == "2023 sept":
            clean_title = "2023 September"

        return (
            f"Here is the {subject} {clean_title} question paper:\n\n"
            f"{PUBLIC_FIRST_YEAR_URL}"
        )

    # Programming in C specific phrasing requested by prompt
    if subject.lower() == "programming in c" and "cprog" in title.lower():
        return (
            f"Here is the Programming in C — {title} notes:\n\n"
            f"{PUBLIC_FIRST_YEAR_URL}"
        )

    # Notes formatting
    if unit_str and unit_str.strip().lower() in title.lower():
        return (
            f"Here is the {subject} {title} notes:\n\n"
            f"{PUBLIC_FIRST_YEAR_URL}"
        )
    elif unit_str:
        return (
            f"Here is the {subject}{unit_str} ({title}) notes:\n\n"
            f"{PUBLIC_FIRST_YEAR_URL}"
        )
    else:
        return (
            f"Here is the {subject} — {title} notes:\n\n"
            f"{PUBLIC_FIRST_YEAR_URL}"
        )


def _format_clarification_response(
    matching_candidates: List[Dict[str, Any]],
    subject: str,
    unit: Optional[int],
    doc_type: str
) -> str:
    """
    Format a concise, unambiguous clarification question.
    Example: "Which Physics Unit 1 notes do you want: Lasers or Optical Fibres?"
    """
    cand_labels = []
    for c in matching_candidates:
        t = c.get("title", "").strip()
        m_paren = re.search(r'\((.*?)\)', t)
        if m_paren:
            cand_labels.append(m_paren.group(1).strip())
        else:
            clean_t = re.sub(r'^(?:unit\s*[-_]?\s*\d+|cie\s*\d+)\s*[-:]?\s*', '', t, flags=re.I).strip(" ()-")
            cand_labels.append(clean_t if clean_t else t)

    options_str = " or ".join(cand_labels)
    unit_str = f" Unit {unit}" if unit is not None else ""
    dt_str = "question papers" if doc_type == "question_paper" else "notes"
    return f"Which {subject}{unit_str} {dt_str} do you want: {options_str}?"


def resolve_academic_followup(
    message: str,
    student_id: str,
    session_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Attempt to resolve user message as a follow-up to a pending academic document candidate query.
    Returns response dict if resolved or clarification needed, or None if message is unrelated
    or not an academic candidate selection.
    """
    key = session_id or student_id
    context = None
    if session_id:
        sess_ctx = get_session_context(session_id)
        context = sess_ctx.get("pending_academic")
    if not context:
        context = get_academic_context(student_id)

    if not context or not context.get("awaiting_selection"):
        return None

    clean_msg = message.strip()
    if not clean_msg:
        return None

    low_msg = clean_msg.lower()
    clean_norm = re.sub(r'[^\w\s\(\)&+-]', ' ', low_msg).strip()

    # 1. Unrelated Intent Check:
    # Do not hijack greetings, identity, profile queries/updates, department, or club queries
    from backend.agent import classify_intent
    classified = classify_intent(clean_msg)
    if classified.get("type") in (
        "greeting", "identity", "memory_query", "memory_update",
        "preference_clear", "department", "club", "agentic"
    ):
        clear_academic_context(student_id)
        if session_id:
            clear_academic_context(session_id)
        return None

    greeting_patterns = [
        r'^(?:hi|hello|hey|hola|sup|yo)\b',
        r'^(?:good\s+(?:morning|afternoon|evening|day))\b',
        r'^(?:thanks|thank\s+you(?:\s+so\s+much)?|thanks\s+a\s+lot)\b',
        r'^(?:bye|goodbye|see\s+you|cya)\b'
    ]
    if any(re.search(p, clean_norm) for p in greeting_patterns):
        clear_academic_context(student_id)
        if session_id:
            clear_academic_context(session_id)
        return None

    # Check if user explicitly asked for a different subject
    from backend.documents import normalize_subject
    mentioned_subj = normalize_subject(clean_norm)
    pending_subj = context.get("subject")
    if mentioned_subj and pending_subj and mentioned_subj.lower() != pending_subj.lower():
        clear_academic_context(student_id)
        if session_id:
            clear_academic_context(session_id)
        return None

    candidates: List[Dict[str, Any]] = context.get("candidates", [])
    if not candidates:
        clear_academic_context(student_id)
        if session_id:
            clear_academic_context(session_id)
        return None

    # 2. Check Ordinal / Number Reference
    ordinal_patterns: List[Tuple[str, int]] = [
        (r'^\s*(?:the\s+)?(?:first|1st|1|#1)(?:\s+one)?\s*$', 0),
        (r'^\s*(?:the\s+)?(?:second|2nd|2|#2)(?:\s+one)?\s*$', 1),
        (r'^\s*(?:the\s+)?(?:third|3rd|3|#3)(?:\s+one)?\s*$', 2),
        (r'^\s*(?:the\s+)?(?:fourth|4th|4|#4)(?:\s+one)?\s*$', 3),
        (r'^\s*(?:the\s+)?(?:fifth|5th|5|#5)(?:\s+one)?\s*$', 4),
        (r'^\s*(?:the\s+)?last(?:\s+one)?\s*$', -1),
        (r'\b(?:give\s+me|i\s+want|show\s+me|select)?\s*(?:the\s+)?(?:first|1st|#1)(?:\s+one)?\b', 0),
        (r'\b(?:give\s+me|i\s+want|show\s+me|select)?\s*(?:the\s+)?(?:second|2nd|#2)(?:\s+one)?\b', 1),
        (r'\b(?:give\s+me|i\s+want|show\s+me|select)?\s*(?:the\s+)?(?:third|3rd|#3)(?:\s+one)?\b', 2),
    ]
    for pat, idx in ordinal_patterns:
        if re.search(pat, clean_norm):
            target_idx = idx if idx >= 0 else len(candidates) - 1
            if 0 <= target_idx < len(candidates):
                selected = candidates[target_idx]
                clear_academic_context(student_id)
                if session_id:
                    clear_academic_context(session_id)
                ans = format_resolved_document_response(selected, pending_subj, context.get("document_type", "notes"))
                return {
                    "answer": ans,
                    "action_taken": "academic_followup_resolution",
                    "sources": [{
                        "title": selected.get("title", ""),
                        "subject": selected.get("subject", pending_subj),
                        "public_url": PUBLIC_FIRST_YEAR_URL,
                        "file_path": selected.get("local_file_path", "")
                    }]
                }

    # 3. Content and Keyword Matching against Candidate Documents
    user_tokens = set(_tokenize(clean_msg))
    if not user_tokens:
        return None

    cand_tokens_list = [_tokenize(c.get("title", "")) for c in candidates]

    common_tokens = set()
    if len(cand_tokens_list) > 1:
        common_tokens = set(cand_tokens_list[0])
        for c_toks in cand_tokens_list[1:]:
            common_tokens &= set(c_toks)

    candidate_scores: List[float] = []
    exact_matches: List[int] = []

    for i, cand in enumerate(candidates):
        c_title = cand.get("title", "").strip().lower()
        c_clean = _clean_text(c_title)
        score = 0.0

        if clean_norm == c_clean:
            score += 1000.0
            exact_matches.append(i)
        elif clean_norm in c_clean or c_clean in clean_norm:
            score += 500.0

        c_toks = set(cand_tokens_list[i])
        for u_tok in user_tokens:
            if u_tok in c_toks:
                if u_tok in common_tokens:
                    score += 1.0
                else:
                    score += 10.0
            else:
                for ct in c_toks:
                    if len(u_tok) >= 4 and len(ct) >= 4 and (u_tok in ct or ct in u_tok):
                        if ct in common_tokens:
                            score += 1.0
                        else:
                            score += 8.0
                        break

        candidate_scores.append(score)

    max_score = max(candidate_scores) if candidate_scores else 0.0

    if max_score <= 0.0:
        return None

    matching_indices = [i for i, s in enumerate(candidate_scores) if s >= max_score * 0.8 and s > 0.0]

    if len(matching_indices) == 1 or (len(candidate_scores) > 1 and max_score >= 10.0 and sorted(candidate_scores, reverse=True)[0] > sorted(candidate_scores, reverse=True)[1] + 5.0):
        best_idx = candidate_scores.index(max_score)
        selected = candidates[best_idx]
        clear_academic_context(student_id)
        if session_id:
            clear_academic_context(session_id)
        ans = format_resolved_document_response(selected, pending_subj, context.get("document_type", "notes"))
        return {
            "answer": ans,
            "action_taken": "academic_followup_resolution",
            "sources": [{
                "title": selected.get("title", ""),
                "subject": selected.get("subject", pending_subj),
                "public_url": PUBLIC_FIRST_YEAR_URL,
                "file_path": selected.get("local_file_path", "")
            }]
        }

    # Ambiguous selection: ask a concise clarification without discarding context
    ambig_candidates = [candidates[i] for i in matching_indices] if len(matching_indices) > 1 else candidates
    clarification_msg = _format_clarification_response(
        ambig_candidates,
        pending_subj,
        context.get("unit"),
        context.get("document_type", "notes")
    )
    return {
        "answer": clarification_msg,
        "action_taken": "academic_followup_clarification",
        "sources": []
    }


def _extract_recent_department_from_history(
    history: List[Dict[str, Any]],
    current_context: Dict[str, Any]
) -> Optional[str]:
    """Inspect session context or recent conversation history to identify the active department."""
    # 1. From active session context
    if current_context.get("last_department"):
        return current_context["last_department"]

    # 2. From recent history messages
    if not history:
        return None

    from backend.info_lookup import BRANCH_ALIASES
    sorted_aliases = sorted(BRANCH_ALIASES.keys(), key=len, reverse=True)

    for msg in reversed(history[-4:]):
        content = (msg.get("content") or "").lower()
        # Skip pure generic pronouns
        for alias in sorted_aliases:
            if alias in ("me", "is", "ai"):
                continue
            pat = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
            if re.search(pat, content):
                return BRANCH_ALIASES[alias]

    return None


def _extract_recent_topic_from_history(
    history: List[Dict[str, Any]],
    current_context: Dict[str, Any]
) -> Optional[str]:
    """Inspect session context or recent conversation history to identify the active academic topic."""
    # 1. From active session context
    if current_context.get("last_topic"):
        return current_context["last_topic"]

    # 2. From recent history messages
    if not history:
        return None

    topic_regexes = [
        r'\b(?:explain|what\s+is|tell\s+me\s+about|how\s+does|overview\s+of)\s+([a-zA-Z0-9\s-]+?)(?:\?|$|\.|\n)',
        r'\b([a-zA-Z0-9\s-]+?\b(?:mechanism|reaction|theorem|law|effect|cell|laser|fibres?|calculus))\b'
    ]

    for msg in reversed(history[-4:]):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            for r in topic_regexes:
                m = re.search(r, content, re.I)
                if m:
                    cand = m.group(1).strip()
                    if len(cand) >= 4 and cand.lower() not in ("it", "this", "that", "something", "more"):
                        return cand

    return None


def resolve_conversation_context(
    message: str,
    student_id: str,
    session_id: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Resolve multi-turn conversation context BEFORE routing.
    Does NOT force requests through RAG. After resolution, lets the deterministic router
    decide the destination (department lookup, document search, RAG, MCP, etc.).

    Returns:
    {
        "is_direct_answer": bool,
        "result": Optional[Dict[str, Any]],     # set if resolved directly (e.g. academic candidate selection)
        "resolved_message": str,                 # message with resolved entities/pronouns
        "context_type": Optional[str]            # 'academic_selection', 'entity_followup', 'explanation_followup'
    }
    """
    clean_msg = message.strip()
    key = session_id or student_id
    ctx = get_session_context(key)
    recent_history = history or []

    # 1. Check for Academic Candidate Follow-up (e.g. "laser", "2023 May", "the first one")
    academic_res = resolve_academic_followup(clean_msg, student_id, session_id)
    if academic_res is not None:
        return {
            "is_direct_answer": True,
            "result": academic_res,
            "resolved_message": clean_msg,
            "context_type": "academic_selection"
        }

    # 2. Stale Context Guard: If query is an explicit reset, greeting, or fresh identity query,
    # do NOT apply previous pronoun or topic context.
    clean_low = clean_msg.lower()
    clearing_patterns = [
        r'^(?:hi|hello|hey|good\s+(?:morning|evening|afternoon)|thanks|thank\s+you|bye|goodbye)\b',
        r'^(?:who\s+are\s+you|what\s+can\s+you\s+do|help|what\s+are\s+you)\b',
        r'\b(?:my\s+(?:name|branch|semester|cgpa)\s+is|update\s+my\s+profile)\b'
    ]
    if any(re.search(p, clean_low) for p in clearing_patterns):
        # Clear candidate context and return original message unmodified
        clear_academic_context(student_id)
        if session_id:
            clear_academic_context(session_id)
        return {
            "is_direct_answer": False,
            "result": None,
            "resolved_message": clean_msg,
            "context_type": None
        }

    # 3. Entity & Pronoun Follow-up Resolution (e.g., "Where is his department?" / "Where is her office?")
    dept_entity = _extract_recent_department_from_history(recent_history, ctx)
    if dept_entity:
        pronoun_dept_patterns = [
            (r'\b(?:where\s+is\s+)?(?:his|her|their|its)\s+department\b', f"Where is the {dept_entity} department?"),
            (r'\b(?:where\s+is\s+)?(?:his|her|their|its)\s+dept\b', f"Where is the {dept_entity} department?"),
            (r'\b(?:where\s+is\s+)?(?:his|her|their)\s+office\b', f"Where is the {dept_entity} department located?"),
            (r'\b(?:where\s+is\s+)?(?:his|her|their)\s+cabin\b', f"Where is the {dept_entity} department located?"),
            (r'^\s*where\s+is\s+(?:it|he|she|this)\s*(?:located)?\s*\??\s*$', f"Where is the {dept_entity} department located?"),
            (r'\b(?:which|what)\s+block\s+is\s+(?:it|he|she|the\s+department|his\s+office|her\s+office)\s+(?:in|located\s+in)?\b', f"Which block is the {dept_entity} department in?"),
            (r'\b(?:what\s+is\s+)?(?:his|her|their)\s+email\b', f"What is the email of the HOD of {dept_entity}?"),
            (r'\b(?:what\s+is\s+)?(?:his|her|their)\s+contact\b', f"What is the contact of the HOD of {dept_entity}?"),
            (r'^\s*who\s+is\s+(?:the\s+)?(?:hod|head)\s*\??\s*$', f"Who is the HOD of {dept_entity}?"),
            (r'^\s*where\s+is\s+(?:the\s+)?(?:department|dept)\s*\??\s*$', f"Where is the {dept_entity} department?")
        ]
        for pat, resolved in pronoun_dept_patterns:
            if re.search(pat, clean_low):
                print(f"[Context Resolver] Resolved pronoun query {clean_msg!r} -> {resolved!r} (dept: {dept_entity})", file=sys.stderr)
                return {
                    "is_direct_answer": False,
                    "result": None,
                    "resolved_message": resolved,
                    "context_type": "entity_followup"
                }

    # 4. Explanation Continuation Resolution (e.g., "What happens at the cathode?" / "Explain it simply")
    academic_topic = _extract_recent_topic_from_history(recent_history, ctx)
    if academic_topic:
        explanation_patterns = [
            (r'^\s*(?:what\s+happens\s+at\s+the\s+cathode|at\s+the\s+cathode)\s*\??\s*$', f"Regarding {academic_topic}, what happens at the cathode?"),
            (r'^\s*(?:what\s+happens\s+at\s+the\s+anode|at\s+the\s+anode)\s*\??\s*$', f"Regarding {academic_topic}, what happens at the anode?"),
            (r'\b(?:can\s+you\s+)?(?:explain\s+it\s+(?:more\s+)?simply|explain\s+simply|in\s+simple\s+terms)\b', f"Explain {academic_topic} simply"),
            (r'\b(?:can\s+you\s+)?(?:give\s+(?:an?\s+)?example|give\s+examples)\b', f"Give an example of {academic_topic}"),
            (r'\b(?:can\s+you\s+)?explain\s+(?:it\s+)?in\s+(?:more\s+)?detail\b', f"Explain {academic_topic} in detail"),
            (r'^\s*what\s+are\s+(?:its|the)\s+applications\s*\??\s*$', f"What are the applications of {academic_topic}?"),
            (r'^\s*what\s+are\s+(?:its|the)\s+advantages\s*\??\s*$', f"What are the advantages of {academic_topic}?"),
            (r'^\s*what\s+are\s+(?:its|the)\s+disadvantages\s*\??\s*$', f"What are the disadvantages of {academic_topic}?")
        ]
        for pat, resolved in explanation_patterns:
            if re.search(pat, clean_low):
                print(f"[Context Resolver] Resolved explanation follow-up {clean_msg!r} -> {resolved!r} (topic: {academic_topic})", file=sys.stderr)
                return {
                    "is_direct_answer": False,
                    "result": None,
                    "resolved_message": resolved,
                    "context_type": "explanation_followup"
                }

    return {
        "is_direct_answer": False,
        "result": None,
        "resolved_message": clean_msg,
        "context_type": None
    }


def update_session_context_from_interaction(
    key: str,
    user_msg: str,
    result: Dict[str, Any]
) -> None:
    """
    Update session context state after a request is handled.
    Records active department, active academic topic, and candidates.
    """
    if not key:
        return
    ctx = get_session_context(key)
    ctx["last_updated"] = time.time()

    action = result.get("action_taken", "")
    low_user = user_msg.lower()

    # Track department
    from backend.info_lookup import BRANCH_ALIASES
    sorted_aliases = sorted(BRANCH_ALIASES.keys(), key=len, reverse=True)
    found_dept = None
    for alias in sorted_aliases:
        if alias in ("me", "is", "ai"):
            continue
        pat = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
        if re.search(pat, low_user):
            found_dept = BRANCH_ALIASES[alias]
            break

    if found_dept:
        ctx["last_department"] = found_dept
    elif action in ("lookup_department", "department_lookup"):
        # Extracted from answer if possible
        ans = result.get("answer", "")
        for alias in sorted_aliases:
            if alias in ("me", "is", "ai"):
                continue
            if alias in ans.lower():
                ctx["last_department"] = BRANCH_ALIASES[alias]
                break

    # Track academic topic from RAG questions
    if action in ("answer_question", "summarize_notes") or "explain" in low_user or "mechanism" in low_user:
        topic_m = re.search(r'\b(?:explain|what\s+is|tell\s+me\s+about|how\s+does)\s+([a-zA-Z0-9\s-]+?)(?:\?|$|\.|\n)', low_user, re.I)
        if topic_m:
            cand_topic = topic_m.group(1).strip()
            if len(cand_topic) >= 4 and cand_topic.lower() not in ("it", "this", "that", "more", "simply"):
                ctx["last_topic"] = cand_topic

    set_session_context(key, ctx)
