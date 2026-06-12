"""FastAPI application — the HTTP layer over the agent.

Endpoints:
  GET  /api/conversations?user_id=       List a user's conversations
  POST /api/conversations                Create a new conversation
  GET  /api/conversations/{id}/history   Load summary + last 6 messages for display
  POST /api/chat                         Send a message, get an agent response

The frontend is served as static files from ../frontend/.
Run with: python api/main.py  (from anywhere)
"""
from __future__ import annotations

# Ensure exercise/ is on sys.path regardless of how this file is invoked
# (python api/main.py, python -m api.main, uvicorn api.main:app, etc.)
import sys
from pathlib import Path as _Path

_EXERCISE_ROOT = _Path(__file__).resolve().parents[1]
if str(_EXERCISE_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXERCISE_ROOT))

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent import loop as agent_loop
from agent.db import Database
from agent.history import (
    create_conversation,
    get_conversation_for_display,
    get_user_conversations,
    init_db,
)
from api.fingerprint import validate_user_id
from api.models import ChatRequest, NewConversationRequest

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger("agentic_bi")
_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_dotenv(_ENV_PATH)
    logger.info("Connecting to Azure Blob / DuckDB …")
    db = Database.connect()
    app.state.db = db
    logger.info("Initialising PostgreSQL schema …")
    init_db()
    logger.info("Agentic BI assistant ready on http://127.0.0.1:8000")
    yield
    db.close()
    logger.info("Shutdown complete.")


app = FastAPI(title="Agentic BI Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Conversations ────────────────────────────────────────────────────────────

@app.get("/api/conversations")
def list_conversations(user_id: str) -> list[dict]:
    try:
        uid = validate_user_id(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_user_conversations(uid)


@app.post("/api/conversations")
def new_conversation(req: NewConversationRequest) -> dict[str, str]:
    try:
        uid = validate_user_id(req.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    conv_id = create_conversation(uid, req.title)
    return {"conversation_id": conv_id}


@app.get("/api/conversations/{conversation_id}/history")
def conversation_history(conversation_id: str) -> dict[str, Any]:
    return get_conversation_for_display(conversation_id)


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    try:
        validate_user_id(req.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db: Database = app.state.db
    return agent_loop.run(req.conversation_id, req.message, db)


# ── Static frontend ──────────────────────────────────────────────────────────

if _FRONTEND_DIR.exists():
    # API routes above are matched first; everything else falls through to the SPA.
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
