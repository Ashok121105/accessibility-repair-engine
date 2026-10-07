from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.app.agent.service import AgentError, agent_sessions, validate_flipkart_url

router = APIRouter()


class AgentStartRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def require_allowed_target(cls, value: str) -> str:
        try:
            return validate_flipkart_url(value)
        except AgentError as error:
            raise ValueError(str(error)) from error


class AgentCommandRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=500)
    preferred_language: Literal["en", "te", "hi", "ta"] | None = None
    language_locked: bool | None = None


class AgentStopRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class AgentCommandResponse(BaseModel):
    success: bool
    action: str
    message: str
    page_url: str
    details: dict[str, Any]
    session_active: bool
    website: str | None = None
    url: str | None = None


@router.post("/agent/start")
async def start_agent(request: AgentStartRequest) -> dict[str, object]:
    try:
        return await agent_sessions.start(request.url)
    except AgentError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/agent/command", response_model=AgentCommandResponse)
async def agent_command(request: AgentCommandRequest) -> dict[str, object]:
    try:
        language_options: dict[str, str | bool] = {}
        if request.preferred_language is not None:
            language_options["preferred_language"] = request.preferred_language
        if request.language_locked is not None:
            language_options["language_locked"] = request.language_locked
        return await agent_sessions.command(request.session_id, request.command, **language_options)
    except AgentError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/agent/stop")
async def stop_agent(request: AgentStopRequest) -> dict[str, str]:
    try:
        return await agent_sessions.stop(request.session_id)
    except AgentError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
