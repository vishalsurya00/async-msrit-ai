"""
Conversation Context and Pending Academic Follow-up Resolver for RIT NEXUS.
Maintains lightweight, per-conversation/in-memory state for academic document interactions.
Resolves short follow-up requests (e.g. "laser unit 1", "2023 May", "Cprog", "the first one")
deterministically without invoking local Qwen LLM.
"""
from typing import Optional, Dict, Any, List, Tuple
import re

PUBLIC_FIRST_YEAR_URL = "https://ritnotebook.pages.dev/notes/first"

# In-memory temporary conversation context storage, keyed by student_id
_PENDING_ACADEMIC_CONTEXTS: Dict[str, Dict[str, Any]] = {}


def get_academic_context(student_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve temporary pending academic context for a student session."""
    return _PENDING_ACADEMIC_CONTEXTS.get(student_id)


def set_academic_context(student_id: str, context: Dict[str, Any]) -> None:
    """Store temporary pending academic context for a student session."""
    _PENDING_ACADEMIC_CONTEXTS[student_id] = context


def clear_academic_context(student_id: str) -> None:
    """Clear temporary pending academic context for a student session."""
    _PENDING_ACADEMIC_CONTEXTS.pop(student_id, None)


def _clean_text(text: str) -> str:
    """Lowercase and strip non-alphanumeric punctuation except common separators."""
    low = text.lower().strip()
    return re.sub(r'[^\w\s\(\)&+-]', ' ', low).strip()


def _tokenize(text: str) -> List[str]:
    """Tokenize into meaningful words and stems."""
    clean = _clean_text(text)
    # Common stopwords/filler words in document queries
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
        # Normalize simple plurals for matching
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
        # Extract title from parentheses if present (e.g. 'Unit 1 (Lasers)' -> 'Lasers')
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


def resolve_academic_followup(message: str, student_id: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to resolve user message as a follow-up to a pending academic document query.
    Returns response dict if resolved or clarification needed, or None if message is unrelated
    or not an academic follow-up.
    """
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
        return None
    greeting_patterns = [
        r'^(?:hi|hello|hey|hola|sup|yo)\b',
        r'^(?:good\s+(?:morning|afternoon|evening|day))\b',
        r'^(?:thanks|thank\s+you(?:\s+so\s+much)?|thanks\s+a\s+lot)\b',
        r'^(?:bye|goodbye|see\s+you|cya)\b'
    ]
    if any(re.search(p, clean_norm) for p in greeting_patterns):
        clear_academic_context(student_id)
        return None

    identity_patterns = [
        r'\b(?:who\s+are\s+you|who\s+r\s+u|what\s+are\s+you|what\s+is\s+your\s+name|what\s+can\s+you\s+do|how\s+can\s+you\s+help|tell\s+me\s+about\s+yourself)\b'
    ]
    if any(re.search(p, clean_norm) for p in identity_patterns):
        clear_academic_context(student_id)
        return None

    memory_query_patterns = [
        r'\b(?:who\s+am\s+i|who\s+i\s+am|tell\s+me\s+who\s+i\s+am|tell\s+me\s+about\s+myself|what\s+do\s+you\s+know\s+about\s+me|show\s+my\s+profile|my\s+profile|my\s+details)\b',
        r'\b(?:what\s+is\s+my\s+(?:name|branch|semester|sem|cgpa|gpa|college|degree)|tell\s+me\s+my\s+(?:name|branch|semester|sem|cgpa|gpa))\b',
        r'\b(?:what|show|tell\s+me)\s+(?:are\s+)?(?:my\s+)?preferences?\b'
    ]
    if any(re.search(p, clean_norm) for p in memory_query_patterns):
        clear_academic_context(student_id)
        return None

    explicit_profile_update_patterns = [
        r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:my\s+)?(?:profile|branch|department|dept|semester|sem|cgpa|gpa|year|college|degree|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\b',
        r'\b(?:my\s+name\s+is|my\s+branch\s+is|my\s+semester\s+is|my\s+cgpa\s+is|my\s+preference\s+is|my\s+main\s+focus\s+is)\b',
        r'\b(?:branch\s*[:=]|semester\s*[:=]|sem\s*[:=]|cgpa\s*[:=]|name\s*[:=]|preference\s*[:=]|focus\s*[:=])\b'
    ]
    if any(re.search(p, clean_norm) for p in explicit_profile_update_patterns):
        clear_academic_context(student_id)
        return None

    dept_patterns = [
        r'\b(?:hod|hoda|head\s+of(?:\s+the)?\s+department)\b',
        r'\b(?:where\s+is|location\s+of|office\s+location)\b.*\b(?:department|dept|block|[a-z]{2,5})\b',
        r'\b(?:who\s+heads|who\s+is\s+the\s+hod|who\s+is\s+hod)\b',
        r'\b(?:what\s+stream\s+is|belongs?\s+to\s+which\s+stream)\b'
    ]
    if any(re.search(p, clean_norm) for p in dept_patterns):
        clear_academic_context(student_id)
        return None

    club_patterns = [
        r'\b(?:coderit|securit|tensor|tnt|edc|rotaract|ieee|sae|debsoc)\b',
        r'\b(?:\w*clubs?|societ(?:y|ies))\w*\b'
    ]
    if any(re.search(p, clean_norm) for p in club_patterns):
        clear_academic_context(student_id)
        return None

    # Check if user explicitly asked for a different subject
    from backend.documents import normalize_subject
    mentioned_subj = normalize_subject(clean_norm)
    pending_subj = context.get("subject")
    if mentioned_subj and pending_subj and mentioned_subj.lower() != pending_subj.lower():
        # User switched subjects explicitly (e.g. from Physics to Chemistry)
        clear_academic_context(student_id)
        return None

    candidates: List[Dict[str, Any]] = context.get("candidates", [])
    if not candidates:
        clear_academic_context(student_id)
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

    # Precompute tokens for each candidate title
    cand_tokens_list = [_tokenize(c.get("title", "")) for c in candidates]

    # Find common tokens across ALL candidates (e.g. "unit", "1" if all candidates are Unit 1)
    common_tokens = set()
    if len(cand_tokens_list) > 1:
        common_tokens = set(cand_tokens_list[0])
        for c_toks in cand_tokens_list[1:]:
            common_tokens &= set(c_toks)

    # Score each candidate
    candidate_scores: List[float] = []
    exact_matches: List[int] = []

    for i, cand in enumerate(candidates):
        c_title = cand.get("title", "").strip().lower()
        c_clean = _clean_text(c_title)
        score = 0.0

        # Exact match
        if clean_norm == c_clean:
            score += 1000.0
            exact_matches.append(i)

        # Full substring match
        elif clean_norm in c_clean or c_clean in clean_norm:
            score += 500.0

        # Token matches
        c_toks = set(cand_tokens_list[i])
        for u_tok in user_tokens:
            if u_tok in c_toks:
                if u_tok in common_tokens:
                    # Common token matches don't help discriminate
                    score += 1.0
                else:
                    # Discriminative token unique to candidate
                    score += 10.0
            else:
                # Substring token match (e.g. "laser" in "lasers" or "calc" in "calculus")
                for ct in c_toks:
                    if len(u_tok) >= 4 and len(ct) >= 4 and (u_tok in ct or ct in u_tok):
                        if ct in common_tokens:
                            score += 1.0
                        else:
                            score += 8.0
                        break

        candidate_scores.append(score)

    max_score = max(candidate_scores) if candidate_scores else 0.0

    # If no candidate matched any terms, this is not an academic follow-up
    if max_score <= 0.0:
        return None

    # Find all candidates achieving high score
    matching_indices = [i for i, s in enumerate(candidate_scores) if s >= max_score * 0.8 and s > 0.0]

    # Check for unambiguous winner
    # A single candidate has significantly higher score or has unique discriminating tokens
    if len(matching_indices) == 1 or (len(candidate_scores) > 1 and max_score >= 10.0 and sorted(candidate_scores, reverse=True)[0] > sorted(candidate_scores, reverse=True)[1] + 5.0):
        best_idx = candidate_scores.index(max_score)
        selected = candidates[best_idx]
        clear_academic_context(student_id)
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

    # If multiple candidates matched and none is clearly superior:
    # Example: User said "Unit 1" when choices are "Unit 1 (Lasers)" and "Unit 1 (Optical Fibres)"
    # This is an ambiguous selection. Ask a concise clarification without discarding context.
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
