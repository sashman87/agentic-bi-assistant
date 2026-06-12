"""Pydantic request/response models for the FastAPI layer."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NewConversationRequest(BaseModel):
    user_id: str
    title: str = "New conversation"


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1, max_length=4000)
    user_id: str


class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    conversation_total_tokens: int
    context_mode: str  # 'full' | 'summarised'


class ChatResponse(BaseModel):
    answer: str
    render: str  # 'text' | 'table' | 'bar_chart' | 'line_chart' | 'pie_chart'
    data: dict[str, Any] | None = None
    sql: str | None = None
    needs_clarification: bool = False
    usage: UsageInfo
