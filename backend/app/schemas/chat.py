from pydantic import BaseModel, Field, field_validator

from app.schemas.property import PropertyOut


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    conversation_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty.")
        return v


class ToolCallInfo(BaseModel):
    name: str
    arguments: dict


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    properties: list[PropertyOut] = []
    tool_calls: list[ToolCallInfo] = []
    history_reset: bool = False  # earlier turns were no longer stored
