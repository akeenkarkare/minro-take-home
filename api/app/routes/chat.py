from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.llm import chat as chat_svc


router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[dict[str, Any]]
    usage: dict[str, Any]


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest, session: AsyncSession = Depends(get_session)
) -> ChatResponse:
    try:
        result = await chat_svc.chat(session, body.message)
    except RuntimeError as e:
        # ANTHROPIC_API_KEY missing -> bubble up cleanly.
        raise HTTPException(status_code=503, detail=str(e)) from e
    return ChatResponse(**result)
