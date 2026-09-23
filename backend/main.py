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
    Routes queries to RAG or audited MCP tools and returns grounded answers.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        result = await handle_message(
            message=payload.message,
            student_id=payload.student_id or "anonymous"
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error processing request: {str(e)}")


# Serve static frontend files (must be mounted after API routes)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
