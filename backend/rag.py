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
    top_k: int = 5
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

    # Check student profile for context filters (stream/cycle)
    stream = None
    cycle = None
    if student_id:
        profile = get_student_profile(student_id)
        if profile:
            stream = profile.get("stream")
            cycle = profile.get("cycle")

    try:
        # Retrieve chunks
        chunks = search_notes(query=query, stream=stream, cycle=cycle, top_k=top_k)

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
            answer = "I could not find any notes or materials related to your question in the database."
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

        prompt = (
            "You are MSRIT AI, a sovereign academic assistant for Ramaiah Institute of Technology students.\n"
            "Answer the question ONLY using the provided context below. Be concise, direct, and helpful.\n"
            "If the provided context does not contain enough information to answer the question, clearly state:\n"
            "\"The provided course notes do not contain sufficient information to answer this question.\"\n"
            "Do not hallucinate or use ungrounded external knowledge.\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {query}\n\n"
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
            "You are MSRIT AI, a sovereign academic assistant for Ramaiah Institute of Technology students.\n"
            f"Summarize the key points, core formulas, and major concepts from these notes on '{clean_subject}'.\n"
            "Use clear bullet points and stay strictly grounded in the provided notes.\n\n"
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
        return {
            "summary": f"Error summarizing notes for '{subject}': {e}",
            "subject": subject,
            "sources": []
        }
