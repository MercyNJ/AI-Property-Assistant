from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from openai import OpenAI

from app.ai.assistant import AssistantError, PropertyAssistant
from app.ai.conversation_store import ConversationStore
from app.api.rate_limit import ChatRateLimiter
from app.config import get_settings


@lru_cache
def get_conversation_store() -> ConversationStore:
    return ConversationStore(max_turns=get_settings().max_history_turns)


@lru_cache
def _build_assistant() -> PropertyAssistant:
    settings = get_settings()
    # Retries are handled in PropertyAssistant._create so they stay within the turn budget.
    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout, max_retries=0)
    return PropertyAssistant(client, settings, get_conversation_store())


@lru_cache
def get_chat_limiter() -> ChatRateLimiter:
    s = get_settings()
    return ChatRateLimiter(s.chat_limit_per_minute, s.chat_limit_per_day, s.chat_limit_global_per_day)


def enforce_chat_rate_limit(request: Request, limiter: ChatRateLimiter = Depends(get_chat_limiter)) -> None:
    # Behind Render's proxy this is the forwarded client IP (see render.yaml).
    client = request.client.host if request.client else "unknown"
    if limited := limiter.check(client):
        raise HTTPException(status_code=429, detail=limited.message,
                            headers={"Retry-After": str(limited.retry_after)})


def get_assistant() -> PropertyAssistant:
    if not get_settings().ai_configured:
        raise AssistantError(
            "The AI assistant is not configured. Set OPENAI_API_KEY in the backend environment and restart.", 503
        )
    return _build_assistant()
