"""
Agentic Tool Selection and Execution Module for RIT NEXUS.
Step 4B: Controlled Agentic Tool Selection with strict max tool calls (default 3),
local Qwen 2.5:7B reasoning, PostgreSQL/local documents authoritative grounding,
and strict profile write safety (no inferred profile updates).
"""
from typing import Dict, Any, List, Optional, Tuple
import json
import re
import sys
import time
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend import mcp_client
from backend.rag import OLLAMA_URL, OLLAMA_MODEL

MAX_TOOL_CALLS = 3

ALLOWED_TOOLS = {
    "lookup_department",
    "lookup_club",
    "search_academic_documents",
    "get_academic_document",
    "get_student_profile",
    "update_student_profile",
    "get_academic_context",
    "get_recommended_clubs",
    "lookup_principal",
    "lookup_proctor",
    "lookup_campus_office",
    "get_entity_counts",
}

TOOL_REGISTRY = {
    "lookup_department": {
        "description": "Look up official MSRIT engineering department details such as department code, full name, HOD, and location.",
        "arguments": {
            "query": "string (e.g., 'CSE', 'ME', 'Civil', 'AI&ML', 'CSE(AI&ML)', 'ECE')"
        },
        "required": ["query"]
    },
    "lookup_club": {
        "description": "Search student technical and cultural clubs, student chapters, and societies at MSRIT.",
        "arguments": {
            "query": "optional string (e.g., 'CodeRIT', 'SecuRIT')",
            "category": "optional string (e.g., 'Technical', 'Cultural')"
        },
        "required": []
    },
    "search_academic_documents": {
        "description": "Search verified academic notes, syllabus files, question papers, and lab manuals by subject, unit, or keywords.",
        "arguments": {
            "subject": "optional string (e.g., 'Mathematics', 'Physics', 'Chemistry', 'Programming in C')",
            "unit": "optional integer (e.g., 1, 2, 3)",
            "query": "optional keyword string",
            "document_type": "optional string ('notes', 'question_paper', 'lab_manual', 'syllabus')"
        },
        "required": []
    },
    "get_academic_document": {
        "description": "Retrieve exact verified metadata and local file path for a specific academic document by document_id.",
        "arguments": {
            "document_id": "string (the exact unique document_id)"
        },
        "required": ["document_id"]
    },
    "get_student_profile": {
        "description": "Retrieve the persistent profile of the current student (name, college, degree, branch, semester, CGPA).",
        "arguments": {
            "student_id": "string (the student ID)"
        },
        "required": ["student_id"]
    },
    "update_student_profile": {
        "description": "Update the student's profile in database memory. WRITE OPERATION: ONLY use when the user EXPLICITLY asks to update or record profile data.",
        "arguments": {
            "student_id": "string (the student ID)",
            "branch": "optional string (e.g. 'CSE(AI&ML)', 'AI&ML', 'ECE')",
            "semester": "optional integer (1 to 10)",
            "name": "optional string",
            "cgpa": "optional float (0.0 to 10.0)"
        },
        "required": ["student_id"]
    },
    "get_academic_context": {
        "description": "Resolve multi-hop academic curriculum relationships connecting student, branch, curricular stream, cycle, enrolled subjects, and document counts.",
        "arguments": {
            "student_id": "optional string (current student ID)",
            "branch": "optional string (e.g. 'CSE', 'AI&ML', 'CSE(AI&ML)', 'ME')",
            "cycle": "optional string ('Physics Cycle' or 'Chemistry Cycle')"
        },
        "required": []
    },
    "get_recommended_clubs": {
        "description": "Search and recommend student clubs based on branch eligibility (branch_scope) and optional category.",
        "arguments": {
            "branch": "optional string (e.g. 'ME', 'CSE', 'AI&ML', 'ECE')",
            "category": "optional string ('Technical', 'Cultural', 'Outreach', 'Literary')"
        },
        "required": []
    },
    "lookup_principal": {
        "description": "Retrieve verified institutional details about the Principal of MSRIT (name, role, office location, contact, joined date, education).",
        "arguments": {},
        "required": []
    },
    "lookup_proctor": {
        "description": "Retrieve verified institutional details about the Chief Proctor of MSRIT (name, role, department, office location, responsibilities).",
        "arguments": {},
        "required": []
    },
    "lookup_campus_office": {
        "description": "Retrieve verified campus administrative offices, departments, and building locations (e.g. Apex Block, Ground Floor offices).",
        "arguments": {
            "query": "string (office name or building keyword, e.g. 'Principal Office', 'Apex Block', 'Scholarship')"
        },
        "required": ["query"]
    },
    "get_entity_counts": {
        "description": "Retrieve exact authoritative database counts for branches, departments, or clubs.",
        "arguments": {
            "entity_type": "optional string ('branches', 'clubs', 'departments')"
        },
        "required": []
    }
}

# Explicit profile update patterns to prevent inferred updates
EXPLICIT_UPDATE_REGEXES = [
    r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:my\s+)?(?:profile|branch|department|dept|semester|sem|cgpa|gpa|year|college|degree|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\b',
    r'\b(?:update|change|set|save|record|add|modify|edit|switch)\s+(?:semester|sem|branch|dept|department|cgpa|gpa|year|name|preference|preferences|explanation\s+preference|focus|focus\s+subject)\s+(?:to|with|as|is|=)\b',
    r'\b(?:my\s+branch|my\s+semester|my\s+sem|my\s+cgpa|my\s+gpa|my\s+name|my\s+college|my\s+degree|my\s+year|my\s+preference|my\s+main\s+focus|my\s+focus\s+subject)\s*(?:is|to|as|with|:=|:|:=|=)\b',
    r'\b(?:i\s+am\s+in\s+semester\s+\d+|i\s+am\s+in\s+\d+(?:st|nd|rd|th)?\s+semester|i\s+am\s+in\s+\d+(?:st|nd|rd|th)?\s+sem)\b',
    r'\b(?:i\s+am\s+studying\s+in|i\s+study\s+in)\b',
    r'\b(?:remember\s+that\s+i|remember\s+my)\b',
    r'\b(?:remember\s+that\s+)?(?:i\s+prefer|i\s+like)\s+(?:concise|short|brief|direct|detailed|long|thorough|in-depth|in\s+depth)\b',
    r'\b(?:remember\s+that\s+)?my\s+main\s+focus\s+is\b',
    r'\b(?:clear|reset|forget)\s+(?:my\s+)?preferences?\b',
    r'\b(?:branch\s*[:=]|semester\s*[:=]|sem\s*[:=]|cgpa\s*[:=]|name\s*[:=]|preference\s*[:=]|focus\s*[:=])\b'
]


def is_explicit_profile_update_request(query: str) -> bool:
    """
    Guarantees Profile Write Safety:
    Returns True ONLY if user explicitly commanded a profile update or declared their profile facts.
    Returns False for inferred facts, third-party suggestions, or passive mentions.
    """
    clean = query.lower().strip()
    return any(re.search(pat, clean) for pat in EXPLICIT_UPDATE_REGEXES)


def parse_tool_selection(raw_text: str) -> Dict[str, Any]:
    """
    Extracts and validates structured tool selection from model output.
    Safely rejects malformed JSON, unknown tools, or invalid schemas.
    Returns a dict with action ('tool', 'answer', or 'error').
    """
    if not raw_text or not raw_text.strip():
        return {"action": "error", "error": "Empty tool selection response"}

    clean_text = raw_text.strip()

    # Extract JSON object from markdown code fences if present
    fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', clean_text)
    if fence_match:
        json_str = fence_match.group(1).strip()
    else:
        brace_match = re.search(r'(\{[\s\S]*\})', clean_text)
        if brace_match:
            json_str = brace_match.group(1).strip()
        else:
            json_str = clean_text

    try:
        parsed = json.loads(json_str)
    except Exception as exc:
        return {
            "action": "error",
            "error": f"Malformed tool-selection JSON: {str(exc)}",
            "raw": clean_text
        }

    if not isinstance(parsed, dict):
        return {
            "action": "error",
            "error": "Tool selection output must be a JSON object",
            "raw": clean_text
        }

    action = parsed.get("action")
    if action not in ("tool", "answer"):
        return {
            "action": "error",
            "error": f"Invalid action '{action}'. Must be 'tool' or 'answer'",
            "raw": clean_text
        }

    if action == "answer":
        return {
            "action": "answer",
            "reason": str(parsed.get("reason") or "No tool required")
        }

    # action == "tool"
    tool_name = parsed.get("tool")
    if not tool_name or not isinstance(tool_name, str):
        return {
            "action": "error",
            "error": "Missing 'tool' attribute in tool action",
            "raw": clean_text
        }

    if tool_name not in ALLOWED_TOOLS:
        return {
            "action": "error",
            "error": f"Unknown tool requested: '{tool_name}'",
            "raw": clean_text
        }

    arguments = parsed.get("arguments", {})
    if not isinstance(arguments, dict):
        return {
            "action": "error",
            "error": "'arguments' must be a dictionary",
            "raw": clean_text
        }

    return {
        "action": "tool",
        "tool": tool_name,
        "arguments": arguments
    }


def _build_tool_selection_prompt(query: str, student_id: str, observations: List[Dict[str, Any]]) -> str:
    """
    Constructs the prompt for Qwen 2.5:7B to select the next MCP tool.
    """
    tools_desc = []
    for name, spec in TOOL_REGISTRY.items():
        args_str = ", ".join(f"{k}: {v}" for k, v in spec["arguments"].items())
        tools_desc.append(f"- {name}: {spec['description']}\n  Arguments: {{{args_str}}}")

    tools_text = "\n".join(tools_desc)

    obs_lines = []
    if observations:
        for i, obs in enumerate(observations, 1):
            tool = obs.get("tool", "unknown")
            args = obs.get("arguments", {})
            res = obs.get("result")
            err = obs.get("error")
            if err:
                obs_lines.append(f"Observation {i}: Tool '{tool}' with arguments {args} failed: {err}")
            else:
                summary = json.dumps(res)[:300] if res is not None else "None"
                obs_lines.append(f"Observation {i}: Tool '{tool}' with arguments {args} returned: {summary}")
        observations_text = "\n".join(obs_lines)
    else:
        observations_text = "No tools have been executed yet."

    prompt = f"""You are the Tool Selection Agent for RIT NEXUS, a sovereign AI assistant for Ramaiah Institute of Technology (MSRIT).
Determine which MCP tool (if any) is required to answer the user query based on the verified facts available.

AVAILABLE TOOLS:
{tools_text}

CRITICAL RULES:
1. PostgreSQL and local files are the sole source of truth. Never invent facts.
2. If the user asks about multiple items (e.g., both a department and a club), and only one has been retrieved so far, call the tool for the other item before finishing.
3. If sufficient verified facts have been retrieved to answer ALL parts of the query, return action="answer".
4. If no tool is needed (e.g., pure greeting, out-of-scope query), return action="answer".
5. 'update_student_profile' must ONLY be selected if the user explicitly commanded to save or update profile data.
6. Return ONLY a single JSON object. No explanation or markdown text outside the JSON.

OUTPUT FORMATS:
To call a tool:
{{
  "action": "tool",
  "tool": "<tool_name>",
  "arguments": {{
    "<arg_name>": "<value>"
  }}
}}

When all required information has been gathered:
{{
  "action": "answer",
  "reason": "Sufficient information has been gathered to answer the question"
}}

User Query: "{query}"
Current Student ID: "{student_id}"

{observations_text}

JSON Action:"""
    return prompt


def select_tool_agentic(query: str, student_id: str, observations: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], float]:
    """
    Queries local Qwen 2.5:7B to select the next MCP tool based on query and prior observations.
    Returns (selection_dict, latency_ms).
    """
    t0 = time.perf_counter()
    from backend.language_control import inject_english_instruction
    prompt = inject_english_instruction(_build_tool_selection_prompt(query, student_id, observations))

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 90
                }
            },
            timeout=90
        )
        resp.raise_for_status()
        raw_output = resp.json().get("response", "").strip()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        print(f"[Agentic Selection] Qwen raw output: {raw_output!r} (took {latency_ms}ms)", file=sys.stderr)
        parsed = parse_tool_selection(raw_output)
        return parsed, latency_ms
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        print(f"[Agentic Selection] Ollama call error: {exc}", file=sys.stderr)
        return {"action": "error", "error": str(exc)}, latency_ms


def _format_observations_for_synthesis(observations: List[Dict[str, Any]]) -> str:
    """Formats retrieved observations for the final grounding prompt."""
    if not observations:
        return "No database observations available."

    lines = []
    for i, obs in enumerate(observations, 1):
        tool = obs.get("tool")
        res = obs.get("result")
        err = obs.get("error")
        if err:
            lines.append(f"Tool {tool} failed with error: {err}")
        elif res is None:
            lines.append(f"Tool {tool} returned: No matching record found.")
        elif isinstance(res, list):
            if not res:
                lines.append(f"Tool {tool} returned: 0 items found.")
            else:
                lines.append(f"Tool {tool} returned {len(res)} item(s):")
                for item in res[:5]:
                    if isinstance(item, dict) and tool in ("search_academic_documents", "get_academic_document"):
                        from backend.documents import sanitize_document_metadata
                        safe_item = sanitize_document_metadata(item)
                    else:
                        safe_item = item
                    lines.append(f"  - {json.dumps(safe_item)}")
        elif isinstance(res, dict):
            lines.append(f"Tool {tool} returned record:")
            if tool in ("search_academic_documents", "get_academic_document"):
                from backend.documents import sanitize_document_metadata
                safe_res = sanitize_document_metadata(res)
            else:
                safe_res = res
            for k, v in safe_res.items():
                lines.append(f"  - {k}: {v}")
        else:
            lines.append(f"Tool {tool} returned: {res}")
    return "\n".join(lines)


def _deterministic_synthesis_fallback(query: str, observations: List[Dict[str, Any]]) -> str:
    """
    Deterministic synthesis fallback when Ollama is unavailable.
    Guarantees the system never crashes and strictly reports verified database facts.
    """
    if not observations:
        return "I could not find relevant verified information in the MSRIT database to answer your request."

    parts = []
    for obs in observations:
        tool = obs.get("tool")
        res = obs.get("result")
        err = obs.get("error")

        if err:
            parts.append(f"Unable to retrieve information from {tool}: {err}")
        elif res is None:
            parts.append(f"No records found matching your request in {tool}.")
        elif tool in ("lookup_department", "lookup_branch") and isinstance(res, dict):
            code = res.get("code", "")
            name = res.get("name", "")
            hod = res.get("hod_name", "N/A")
            loc = res.get("location", "N/A")
            stream = res.get("stream", "N/A")
            parts.append(
                f"**Department Information — {name} ({code})**\n"
                f"- **HOD:** {hod}\n"
                f"- **Location:** {loc}\n"
                f"- **Stream:** {stream}"
            )
        elif tool == "lookup_club" and isinstance(res, list):
            if not res:
                parts.append("No clubs found matching your search.")
            else:
                c_lines = ["**MSRIT Student Clubs:**"]
                for c in res[:4]:
                    c_lines.append(f"- **{c.get('name')}** [{c.get('category')}]: {c.get('description', '')}")
                parts.append("\n".join(c_lines))
        elif tool == "search_academic_documents" and isinstance(res, list):
            if not res:
                parts.append("No academic documents found matching your criteria.")
            else:
                d_lines = [f"Found {len(res)} academic document(s):"]
                for d in res[:4]:
                    u_str = f", Unit {d.get('unit')}" if d.get('unit') is not None else ""
                    d_lines.append(f"- **{d.get('title')}** ({d.get('subject')}{u_str})")
                d_lines.append(f"\nResource link: https://ritnotebook.pages.dev/notes/first")
                parts.append("\n".join(d_lines))
        elif tool == "get_student_profile" and isinstance(res, dict):
            p_lines = [f"**Student Profile ({res.get('student_id')}):**"]
            for k in ("name", "college", "degree", "branch", "semester", "cgpa"):
                if res.get(k):
                    p_lines.append(f"- **{k.title()}:** {res.get(k)}")
            parts.append("\n".join(p_lines))
        elif tool == "get_academic_context" and isinstance(res, dict):
            from backend.knowledge import format_academic_context_response
            parts.append(format_academic_context_response(res))
        elif tool == "get_recommended_clubs" and isinstance(res, list):
            from backend.knowledge import format_recommended_clubs_response
            parts.append(format_recommended_clubs_response(res))
        elif isinstance(res, dict):
            parts.append(json.dumps(res, indent=2))
        elif isinstance(res, list):
            parts.append(f"Retrieved {len(res)} items from {tool}.")

    return "\n\n".join(parts)


def synthesize_grounded_answer(query: str, observations: List[Dict[str, Any]], student_id: str) -> Tuple[str, float]:
    """
    Uses local Qwen 2.5:7B to synthesize a natural, helpful response strictly grounded
    in the verified observations retrieved from PostgreSQL/documents.
    Returns (answer_text, latency_ms).
    """
    t0 = time.perf_counter()
    facts_text = _format_observations_for_synthesis(observations)

    pref_rule = ""
    if student_id and student_id != "anonymous":
        try:
            from backend.memory import get_student_profile
            prof = get_student_profile(student_id)
            if prof and isinstance(prof.get("preferences"), dict):
                exp_style = prof["preferences"].get("explanation_style")
                if exp_style == "concise":
                    pref_rule = "\n6. The student explicitly prefers concise answers. Be direct, crisp, and avoid unnecessary background or filler."
                elif exp_style == "detailed":
                    pref_rule = "\n6. The student explicitly prefers detailed answers. Provide a thorough, in-depth explanation with clear structure, steps, or definitions."
        except Exception:
            pass

    prompt = f"""You are MSRIT AI, a sovereign academic assistant for Ramaiah Institute of Technology students.
The student asked: "{query}"

VERIFIED FACTS RETRIEVED FROM LOCAL DATABASE:
{facts_text}

CRITICAL RULES:
1. Base your response strictly and exclusively on the verified facts above.
2. DO NOT invent department locations, HOD names, clubs, syllabus details, or document metadata not present in the facts.
3. If an item was not found or a tool returned empty/none, honestly state that it is not available.
4. If asked about recommendations, recommend ONLY the documents/notes explicitly listed in the facts.
5. NEVER mention local filesystem paths (data/raw/...), internal folder IDs, or storage locations. If referring to notes, use the public link: https://ritnotebook.pages.dev/notes/first.
6. Provide a crisp, helpful, and polite response for the student.{pref_rule}

Answer:"""

    try:
        from backend.language_control import safe_qwen_generate
        from backend.documents import sanitize_text
        fallback = sanitize_text(_deterministic_synthesis_fallback(query, observations))
        answer = safe_qwen_generate(
            prompt,
            deterministic_fallback=fallback,
            timeout=90,
            options={"temperature": 0.2, "num_predict": 280}
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if not answer:
            answer = fallback
        return sanitize_text(answer), latency_ms
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        print(f"[Grounded Synthesis] Ollama call error: {exc}. Using deterministic fallback.", file=sys.stderr)
        from backend.documents import sanitize_text
        return sanitize_text(_deterministic_synthesis_fallback(query, observations)), latency_ms


def _match_branch_helper(query: str, clean: str) -> Optional[str]:
    from backend.info_lookup import BRANCH_ALIASES
    sorted_aliases = sorted(BRANCH_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if alias == "me":
            continue
        pat = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
        if re.search(pat, clean):
            return BRANCH_ALIASES[alias]
    me_dept_pat = r'(?:\b(?:hod|head)\s+(?:of\s+)?me\b|\bme\s+(?:department|dept|branch|office|hod)\b|\b(?:department|dept|branch)\s+of\s+me\b)'
    if re.search(me_dept_pat, clean):
        return "ME"
    return None


def _match_club_helper(clean: str) -> Optional[str]:
    from backend.info_lookup import get_club_lookup_map
    club_map = get_club_lookup_map()
    for c_alias in sorted(club_map.keys(), key=len, reverse=True):
        pat = r'(?:\b|^)' + re.escape(c_alias) + r'(?:\b|$)'
        if re.search(pat, clean):
            return club_map[c_alias]
    return None


def plan_deterministic_tool_sequence(query: str, student_id: str = "") -> Optional[List[Dict[str, Any]]]:
    """
    Identifies high-confidence deterministic multi-tool sequences for multi-domain requests.
    Returns a list of tool call specifications, or None if the request is ambiguous or
    requires LLM agentic reasoning.

    Guarantees:
    - Never plans more than MAX_TOOL_CALLS (3) tools.
    - Preserves agentic reasoning for genuinely combined or ambiguous requests
      (e.g., profile-conditioned academic recommendations).
    - Preserves AI&ML vs CSE(AI&ML) disambiguation.
    - Respects profile-write safety (never plans update_student_profile unless explicitly commanded).
    """
    raw = query.strip()
    low = raw.lower()
    clean = re.sub(r'[^\w\s\(\)&-]', ' ', low).strip()

    # Rule 1: Genuinely combined or ambiguous requests must invoke LLM agentic reasoning
    # e.g., "I'm a semester 3 CSE(AI&ML) student. What Mathematics material should I study?"
    # Queries asking what should I study / recommend / advice based on student profile
    has_advisory = bool(re.search(
        r'\b(?:what\s+.*(?:should\s+i|study)|recommend|suggest|what\s+to\s+study|should\s+i\s+study|which\s+.*(?:should\s+i|study))\b',
        clean
    ))
    has_profile_context = bool(re.search(
        r'\b(?:i\s*(?:am|\'m|m)\b|student\b|semester\s*\d+|sem\s*\d+|my\s+branch|my\s+semester)\b',
        clean
    ))
    if has_advisory and has_profile_context:
        return None

    # Rule 2: Multi-domain detection
    matched_branch = _match_branch_helper(raw, clean)
    has_dept_kw = bool(re.search(
        r'\b(?:hod|hoda|head|leading|leader|department|dept|where|location|office|stream)\b',
        clean
    ))

    matched_club = _match_club_helper(clean)
    has_club_kw = bool(re.search(r'\b(?:clubs?|societ(?:y|ies))\b', clean))
    club_cat = "Technical" if "technical" in clean else ("Cultural" if "cultural" in clean else None)

    # Document detection
    from backend.documents import detect_document_query_params
    doc_params = detect_document_query_params(raw)
    has_doc = bool(
        doc_params.get("subject") or
        doc_params.get("unit") is not None or
        doc_params.get("title_keyword") or
        doc_params.get("document_type")
    ) and not doc_params.get("needs_subject_clarification")

    planned: List[Dict[str, Any]] = []

    # Case A: Department + Club
    if (matched_branch or has_dept_kw) and (matched_club or has_club_kw):
        dept_query = matched_branch if matched_branch else "CSE"
        planned.append({
            "tool": "lookup_department",
            "arguments": {"query": dept_query}
        })
        club_args: Dict[str, Any] = {}
        if matched_club:
            club_args["query"] = matched_club
        if club_cat:
            club_args["category"] = club_cat
        planned.append({
            "tool": "lookup_club",
            "arguments": club_args
        })
        return planned[:MAX_TOOL_CALLS]

    # Case B: Department + Document
    if (matched_branch or has_dept_kw) and has_doc:
        dept_query = matched_branch if matched_branch else "CSE"
        planned.append({
            "tool": "lookup_department",
            "arguments": {"query": dept_query}
        })
        doc_args = {k: v for k, v in doc_params.items() if v is not None and not k.startswith("needs_")}
        planned.append({
            "tool": "search_academic_documents",
            "arguments": doc_args
        })
        return planned[:MAX_TOOL_CALLS]

    # Case C: Club + Document
    if (matched_club or has_club_kw) and has_doc:
        club_args = {}
        if matched_club:
            club_args["query"] = matched_club
        if club_cat:
            club_args["category"] = club_cat
        planned.append({
            "tool": "lookup_club",
            "arguments": club_args
        })
        doc_args = {k: v for k, v in doc_params.items() if v is not None and not k.startswith("needs_")}
        planned.append({
            "tool": "search_academic_documents",
            "arguments": doc_args
        })
        return planned[:MAX_TOOL_CALLS]

    return None


async def run_agentic_workflow(
    query: str,
    student_id: str,
    max_calls: int = MAX_TOOL_CALLS,
    planned_tools: Optional[List[Dict[str, Any]]] = None,
    router_ms: float = 0.0
) -> Dict[str, Any]:
    """
    Executes the controlled agentic tool selection and grounding loop.
    Enforces max tool calls, profile write safety, machine-readable audit logging,
    deterministic sequence fast-path, and returns comprehensive latency metrics.
    """
    t_start = time.perf_counter()
    observations: List[Dict[str, Any]] = []
    tool_calls_record: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []

    total_tool_selection_ms = 0.0
    total_mcp_tool_ms = 0.0
    final_answer_ms = 0.0
    qwen_call_count = 0

    call_count = 0
    clean_sid = student_id.strip() if student_id else "anonymous"

    # Step 0: Check if a deterministic tool sequence is already planned or can be reliably identified
    planned = planned_tools if planned_tools is not None else plan_deterministic_tool_sequence(query, clean_sid)

    if planned and len(planned) >= 2:
        # High-confidence deterministic sequence: execute planned tools directly without Qwen tool selection
        for step in planned[:max_calls]:
            tool_name = step.get("tool")
            tool_args = dict(step.get("arguments", {}))

            if tool_name not in ALLOWED_TOOLS:
                continue

            # Profile safety guardrail
            if tool_name == "update_student_profile":
                if not is_explicit_profile_update_request(query):
                    observations.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "error": "Profile update blocked: Profile memory can only be updated from explicit user statements, not inferred facts.",
                        "result": None,
                        "success": False
                    })
                    tool_calls_record.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": {"error": "Blocked by profile safety rule"},
                        "duration_ms": 0.0,
                        "success": False
                    })
                    break

            if tool_name in ("get_student_profile", "update_student_profile", "get_academic_context") and not tool_args.get("student_id") and clean_sid != "anonymous":
                tool_args["student_id"] = clean_sid

            t_tool0 = time.perf_counter()
            tool_res = await mcp_client.call_tool(tool_name, **tool_args)
            tool_dur_ms = round((time.perf_counter() - t_tool0) * 1000, 2)
            total_mcp_tool_ms += tool_dur_ms
            call_count += 1

            is_err = isinstance(tool_res, dict) and "error" in tool_res
            observations.append({
                "tool": tool_name,
                "arguments": tool_args,
                "result": tool_res,
                "error": tool_res.get("error") if is_err else None,
                "success": not is_err
            })

            tool_calls_record.append({
                "tool": tool_name,
                "arguments": tool_args,
                "result": tool_res,
                "duration_ms": tool_dur_ms,
                "success": not is_err
            })

            if tool_name == "search_academic_documents" and isinstance(tool_res, list):
                from backend.documents import sanitize_source
                for doc in tool_res:
                    sources.append(sanitize_source(doc))

    else:
        # Agentic Reasoning Path: Qwen tool selection loop for combined/ambiguous queries
        while call_count < max_calls:
            # Step 1: LLM Tool Selection
            selection, sel_ms = select_tool_agentic(query, clean_sid, observations)
            total_tool_selection_ms += sel_ms
            qwen_call_count += 1

            action = selection.get("action")

            # Case A: Model decided sufficient info or no tool required
            if action == "answer":
                break

            # Case B: Model returned malformed or unknown tool error
            if action == "error":
                err_msg = selection.get("error", "Invalid tool selection")
                observations.append({
                    "tool": "none",
                    "arguments": {},
                    "error": err_msg,
                    "result": None,
                    "success": False
                })
                # Break safely to avoid infinite looping on errors
                break

            # Case C: Model selected a valid tool
            if action == "tool":
                tool_name = selection.get("tool")
                tool_args = selection.get("arguments", {})

                # Guarantee: Do not execute tools outside allowed registry
                if tool_name not in ALLOWED_TOOLS:
                    observations.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "error": f"Unknown tool: '{tool_name}'",
                        "result": None,
                        "success": False
                    })
                    break

                # Profile Safety Rule: Prevent inferred profile writes
                if tool_name == "update_student_profile":
                    if not is_explicit_profile_update_request(query):
                        observations.append({
                            "tool": tool_name,
                            "arguments": tool_args,
                            "error": "Profile update blocked: Profile memory can only be updated from explicit user statements, not inferred facts.",
                            "result": None,
                            "success": False
                        })
                        tool_calls_record.append({
                            "tool": tool_name,
                            "arguments": tool_args,
                            "result": {"error": "Blocked by profile safety rule"},
                            "duration_ms": 0.0,
                            "success": False
                        })
                        break

                # Ensure student_id is passed if tool expects it and not provided
                if tool_name in ("get_student_profile", "update_student_profile", "get_academic_context") and not tool_args.get("student_id") and clean_sid != "anonymous":
                    tool_args["student_id"] = clean_sid

                # Step 2: Execute MCP Tool
                t_tool0 = time.perf_counter()
                tool_res = await mcp_client.call_tool(tool_name, **tool_args)
                tool_dur_ms = round((time.perf_counter() - t_tool0) * 1000, 2)
                total_mcp_tool_ms += tool_dur_ms
                call_count += 1

                is_err = isinstance(tool_res, dict) and "error" in tool_res
                observations.append({
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": tool_res,
                    "error": tool_res.get("error") if is_err else None,
                    "success": not is_err
                })

                tool_calls_record.append({
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": tool_res,
                    "duration_ms": tool_dur_ms,
                    "success": not is_err
                })

                # Collect document sources if returned
                if tool_name == "search_academic_documents" and isinstance(tool_res, list):
                    from backend.documents import sanitize_source
                    for doc in tool_res:
                        sources.append(sanitize_source(doc))

    # Step 3: Grounded Answer Synthesis (Runs at most once)
    if not observations:
        # No tools were run; provide clean out-of-scope response without calling Qwen
        final_answer = "I'm not sure what you're asking about. I can help with MSRIT departments, clubs, academic notes, and your student profile."
    else:
        final_answer, final_answer_ms = synthesize_grounded_answer(query, observations, clean_sid)
        qwen_call_count += 1

    total_time_ms = round((time.perf_counter() - t_start) * 1000, 2)

    return {
        "answer": final_answer,
        "action_taken": "agentic_tool_execution",
        "sources": sources,
        "tool_calls": tool_calls_record,
        "observations": observations,
        "metrics": {
            "router_ms": round(router_ms, 2),
            "agent_selection_ms": round(total_tool_selection_ms, 2),
            "tool_execution_ms": round(total_mcp_tool_ms, 2),
            "synthesis_ms": round(final_answer_ms, 2),
            "total_ms": total_time_ms,
            "tool_call_count": call_count,
            "qwen_call_count": qwen_call_count,
            # Backward-compatible aliases for Step 4B tests
            "router_time_ms": round(router_ms, 2),
            "tool_selection_time_ms": round(total_tool_selection_ms, 2),
            "mcp_tool_time_ms": round(total_mcp_tool_ms, 2),
            "final_answer_time_ms": round(final_answer_ms, 2),
            "total_time_ms": total_time_ms,
        }
    }
