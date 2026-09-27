"""
RAG (Retrieval-Augmented Generation) module for MSRIT AI.
Retrieves relevant notes chunks, constructs grounded prompts, and queries the local Ollama LLM.
"""
from typing import Optional, List, Dict, Any
import os
import sys
import requests
from backend.search import search_notes
from backend.memory import get_student_profile
from backend.audit import log_action

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")


def answer_question(
    query: str,
    student_id: Optional[str] = None,
    top_k: int = 3
) -> Dict[str, Any]:
    """
    Answer student questions grounded strictly in retrieved course notes.
    Applies profile filters if student_id is provided and calls audit.log_action() before returning.
    """
    if not query or not query.strip():
        result = {"answer": "Please provide a valid question.", "sources": [], "chunks_used": 0}
        log_action(
            tool_name="rag_answer_question",
            student_id=student_id,
            parameters={"query": query, "top_k": top_k},
            result_summary="Empty query received",
            success=False
        )
        return result

    # Check student profile for optional context filters and personalization (failsafe)
    stream = None
    cycle = None
    student_branch = None
    student_sem = None
    preferences = {}
    if student_id:
        try:
            profile = get_student_profile(student_id)
            if profile:
                stream = profile.get("stream")
                cycle = profile.get("cycle")
                student_branch = profile.get("branch")
                student_sem = profile.get("semester")
                preferences = profile.get("preferences") or {}
        except Exception as e:
            print(f"Warning: Optional student profile retrieval in RAG failed gracefully: {e}", file=sys.stderr)

    try:
        from backend.documents import normalize_subject
        detected_subject = normalize_subject(query)
        # If no explicit subject detected in query, check if student has a saved focus_subject
        if not detected_subject and preferences.get("focus_subject"):
            if any(w in query.lower() for w in ["study", "material", "notes", "syllabus", "topics", "learn", "focus"]):
                detected_subject = preferences.get("focus_subject")

        # Retrieve chunks (top_k=3 to keep context focused and avoid broad chapter dumps)
        chunks = []
        if detected_subject:
            chunks = search_notes(query=query, stream=stream, cycle=cycle, subject=detected_subject, top_k=top_k)

        if not chunks:
            chunks = search_notes(query=query, stream=stream, cycle=cycle, top_k=top_k)

        if chunks:
            chunks = chunks[:top_k]

        sources = []
        seen = set()
        for c in chunks:
            fp = c.get("file_path", "")
            if fp and fp not in seen:
                seen.add(fp)
                sources.append({
                    "file_path": fp,
                    "subject": c.get("subject", ""),
                    "source_url": c.get("source_url", "")
                })

        if not chunks:
            answer = "The provided MSRIT notes do not contain this specific information."
            result = {
                "answer": answer,
                "sources": [],
                "chunks_used": 0
            }
            log_action(
                tool_name="rag_answer_question",
                student_id=student_id,
                parameters={"query": query, "top_k": top_k, "stream": stream, "cycle": cycle},
                result_summary="No chunks found",
                success=True
            )
            return result

        # Construct grounded prompt
        context_blocks = []
        for i, chunk in enumerate(chunks, 1):
            fp = chunk.get("file_path", "Note")
            content = chunk.get("content", "").strip()
            context_blocks.append(f"[Document {i} - {fp}]:\n{content}")

        context_text = "\n\n".join(context_blocks)

        # Optional student personalization context
        student_context = ""
        if student_branch and student_sem:
            student_context = f"\nSTUDENT ACADEMIC CONTEXT (Optional): Branch: {student_branch}, Semester: {student_sem}\n"
        elif student_branch:
            student_context = f"\nSTUDENT ACADEMIC CONTEXT (Optional): Branch: {student_branch}\n"
        elif student_sem:
            student_context = f"\nSTUDENT ACADEMIC CONTEXT (Optional): Semester: {student_sem}\n"

        style_instruction = ""
        exp_style = preferences.get("explanation_style")
        if exp_style == "concise":
            style_instruction = (
                "\nSTUDENT EXPLANATION PREFERENCE (Concise Style):\n"
                "- The student explicitly prefers concise answers.\n"
                "- Answer directly and avoid unnecessary background, preamble, or repetition.\n"
                "- Limit the explanation to approximately 1-3 short paragraphs or concise bullet points without omitting necessary factual content.\n"
            )
        elif exp_style == "detailed":
            style_instruction = (
                "\nSTUDENT EXPLANATION PREFERENCE (Detailed Style):\n"
                "- The student explicitly prefers detailed answers.\n"
                "- Provide a thorough, in-depth explanation covering core concepts, definitions, steps, and examples or formulas where appropriate.\n"
                "- Structure the response clearly without irrelevant filler.\n"
            )

        prompt = (
            "You are MSRIT AI, a knowledgeable, friendly academic assistant for Ramaiah Institute of Technology students.\n\n"
            f"USER QUESTION:\n{query}\n\n"
            f"VERIFIED LOCAL MSRIT CONTEXT:\n{context_text}\n"
            f"{student_context}"
            f"{style_instruction}\n"
            "INSTRUCTIONS:\n"
            "1. Explain the requested concept clearly, naturally, and concisely.\n"
            "2. Use the verified local MSRIT material above as your primary grounding source.\n"
            "3. Do not invent MSRIT-specific information (such as fake course codes, fake faculty names, or fake dates).\n"
            "4. If the retrieved notes context lacks specific details about the question, clearly state: "
            "'The available MSRIT notes do not contain full details on this topic, but here is an explanation:' "
            "and provide a clear, accurate explanation of the concept.\n"
            "5. Structure the explanation cleanly using paragraphs or bullet points.\n"
            "6. If student academic context is provided above, you may subtly tailor examples appropriately for a student at that level, while remaining strictly grounded in verified academic facts.\n"
            "7. If an explicit explanation preference is given above, follow that style guideline strictly.\n\n"
            "Answer:"
        )

        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=180
        )
        response.raise_for_status()
        reply_json = response.json()
        answer = reply_json.get("response", "").strip()

        result = {
            "answer": answer,
            "sources": sources,
            "chunks_used": len(chunks)
        }

        log_action(
            tool_name="rag_answer_question",
            student_id=student_id,
            parameters={"query": query, "top_k": top_k, "stream": stream, "cycle": cycle},
            result_summary=f"Success, used {len(chunks)} chunks, response length {len(answer)} chars",
            success=True
        )
        return result

    except Exception as e:
        print(f"Error in answer_question: {e}", file=sys.stderr)
        err_msg = f"Failed to generate answer from local LLM: {str(e)}"
        log_action(
            tool_name="rag_answer_question",
            student_id=student_id,
            parameters={"query": query, "top_k": top_k},
            result_summary=f"Exception: {str(e)}",
            success=False
        )
        if 'chunks' in locals() and chunks:
            fallback_answer = (
                "The local language model is currently unavailable, but here are the verified excerpts from your MSRIT course notes:\n\n"
                + "\n\n---\n\n".join(f"**Excerpt {i+1}** (from `{c.get('source_file')}`):\n{c.get('content', '')[:350]}..." for i, c in enumerate(chunks[:2]))
            )
            return {
                "answer": fallback_answer,
                "sources": sources if 'sources' in locals() else [],
                "chunks_used": len(chunks)
            }
        return {
            "answer": f"Sorry, I encountered an error while querying the local model: {e}",
            "sources": [],
            "chunks_used": 0
        }


def summarize_notes(
    subject: str,
    stream: Optional[str] = None,
    cycle: Optional[str] = None
) -> Dict[str, Any]:
    """
    Summarize key points from course notes for a given subject.
    Calls audit.log_action() before returning.
    """
    if not subject or not subject.strip():
        result = {"summary": "Please provide a valid subject name.", "subject": subject, "sources": []}
        log_action(
            tool_name="rag_summarize_notes",
            student_id=None,
            parameters={"subject": subject, "stream": stream, "cycle": cycle},
            result_summary="Empty subject name provided",
            success=False
        )
        return result

    try:
        clean_subject = subject.strip()
        broad_query = f"{clean_subject} syllabus overview key concepts summary notes"
        chunks = search_notes(query=broad_query, stream=stream, cycle=cycle, top_k=10)

        sources = []
        seen = set()
        for c in chunks:
            fp = c.get("file_path", "")
            if fp and fp not in seen:
                seen.add(fp)
                sources.append({
                    "file_path": fp,
                    "subject": c.get("subject", ""),
                    "source_url": c.get("source_url", "")
                })

        if not chunks:
            summary = f"No notes found for subject '{clean_subject}'."
            result = {"summary": summary, "subject": clean_subject, "sources": []}
            log_action(
                tool_name="rag_summarize_notes",
                student_id=None,
                parameters={"subject": clean_subject, "stream": stream, "cycle": cycle},
                result_summary="No notes found to summarize",
                success=True
            )
            return result

        context_blocks = []
        for i, chunk in enumerate(chunks, 1):
            fp = chunk.get("file_path", "Note")
            content = chunk.get("content", "").strip()
            context_blocks.append(f"[Document {i} - {fp}]:\n{content}")

        context_text = "\n\n".join(context_blocks)

        prompt = (
            "You are MSRIT AI, a precise academic assistant for Ramaiah Institute of Technology students.\n"
            f"Provide a crisp, well-structured bullet-point summary of the core concepts, definitions, and key formulas for '{clean_subject}' based strictly on the provided notes.\n"
            "CRITICAL RULES:\n"
            "1. Avoid vague filler, syllabus outlines, preface text, or course objectives.\n"
            "2. Present key takeaways directly as clean, focused bullet points.\n\n"
            f"Context:\n{context_text}\n\n"
            "Summary:"
        )

        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )
        response.raise_for_status()
        reply_json = response.json()
        summary = reply_json.get("response", "").strip()

        result = {
            "summary": summary,
            "subject": clean_subject,
            "sources": sources
        }

        log_action(
            tool_name="rag_summarize_notes",
            student_id=None,
            parameters={"subject": clean_subject, "stream": stream, "cycle": cycle},
            result_summary=f"Success, summarized {len(chunks)} chunks, length {len(summary)} chars",
            success=True
        )
        return result

    except Exception as e:
        print(f"Error in summarize_notes: {e}", file=sys.stderr)
        log_action(
            tool_name="rag_summarize_notes",
            student_id=None,
            parameters={"subject": subject, "stream": stream, "cycle": cycle},
            result_summary=f"Exception: {str(e)}",
            success=False
        )
        if 'chunks' in locals() and chunks:
            fallback_summary = (
                f"The local language model is currently unavailable, but here are the key verified excerpts from your MSRIT course notes for {subject}:\n\n"
                + "\n\n---\n\n".join(f"- {c.get('content', '')[:300]}..." for c in chunks[:3])
            )
            return {
                "summary": fallback_summary,
                "subject": subject,
                "sources": sources if 'sources' in locals() else []
            }
        return {
            "summary": f"Error summarizing notes for '{subject}': {e}",
            "subject": subject,
            "sources": []
        }
