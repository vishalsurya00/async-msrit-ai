"""
Main FastAPI server for MSRIT AI.
Serves the chat API endpoints and hosts the static frontend UI.
"""
from typing import Optional
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agent import handle_message
from backend.mcp_client import get_mcp_client

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


class AskRequest(BaseModel):
    message: str
    student_id: Optional[str] = "anonymous"
    session_id: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to initialize and gracefully shut down the persistent MCP client."""
    client = get_mcp_client()
    try:
        await client.start()
        print("MSRIT AI: Persistent MCP client session initialized.")
    except Exception as e:
        print(f"Warning: Failed to initialize MCP client at startup: {e}")

    yield

    try:
        await client.close()
        print("MSRIT AI: Persistent MCP client session shut down.")
    except Exception as e:
        print(f"Warning: Error closing MCP client: {e}")


app = FastAPI(
    title="MSRIT AI - Sovereign Academic Assistant",
    description="Fully local, sovereign AI assistant for Ramaiah Institute of Technology students.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local demo and LAN access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Sanity check endpoint returning health status."""
    return {"status": "ok"}


@app.post("/ask")
async def ask_endpoint(payload: AskRequest):
    """
    Primary conversation endpoint.
    Orchestrates session retrieval, context resolution, and message persistence.
    Calls existing handle_message() pipeline with resolved conversation context.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    clean_msg = payload.message.strip()
    student_id = payload.student_id or "anonymous"

    try:
        # 1. Orchestrate session retrieval / creation in PostgreSQL
        from backend.conversation_store import get_or_create_session, add_message, get_recent_messages
        session_id, is_new = get_or_create_session(payload.session_id, student_id=student_id)

        # 2. Retrieve recent conversation history (last 8 messages)
        history = get_recent_messages(session_id, limit=8)

        # 3. Resolve conversation context before routing
        from backend.conversation_context import (
            resolve_conversation_context,
            update_session_context_from_interaction
        )
        context_res = resolve_conversation_context(
            message=clean_msg,
            student_id=student_id,
            session_id=session_id,
            history=history
        )

        # If resolved directly (e.g. academic candidate selection like "2023 May" or "the first one")
        if context_res.get("is_direct_answer") and context_res.get("result"):
            direct_result = context_res["result"]
            add_message(session_id, "user", clean_msg, {"student_id": student_id})
            add_message(session_id, "assistant", direct_result.get("answer", ""), {
                "action_taken": direct_result.get("action_taken"),
                "sources": direct_result.get("sources", [])
            })
            direct_result["session_id"] = session_id
            return direct_result

        # Context-resolved message (e.g. "Where is his department?" -> "Where is the CSE department?")
        resolved_msg = context_res.get("resolved_message", clean_msg)

        # 4. Call existing handle_message() pipeline with resolved query and history
        result = await handle_message(
            message=resolved_msg,
            student_id=student_id,
            conversation_history=history,
            session_id=session_id
        )

        # 5. Persist user and assistant messages
        user_meta = {"student_id": student_id}
        if resolved_msg != clean_msg:
            user_meta["original_message"] = clean_msg
            user_meta["resolved_message"] = resolved_msg
            user_meta["context_type"] = context_res.get("context_type")

        add_message(session_id, "user", clean_msg, user_meta)
        add_message(session_id, "assistant", result.get("answer", ""), {
            "action_taken": result.get("action_taken"),
            "sources": result.get("sources", [])
        })

        # 6. Update session tracking
        update_session_context_from_interaction(session_id, resolved_msg, result)

        # Return result with session_id
        result["session_id"] = session_id
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error processing request: {str(e)}")


# Serve local academic documents from data/raw
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
if DATA_RAW_DIR.exists():
    app.mount("/data/raw", StaticFiles(directory=str(DATA_RAW_DIR)), name="data_raw")

# Serve static frontend files (must be mounted after API routes and document files)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

