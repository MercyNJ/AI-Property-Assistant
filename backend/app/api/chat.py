from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.ai.assistant import PropertyAssistant
from app.ai.conversation_store import ConversationStore
from app.api.deps import enforce_chat_rate_limit, get_assistant, get_conversation_store
from app.database import get_db
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, dependencies=[Depends(enforce_chat_rate_limit)])
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    assistant: PropertyAssistant = Depends(get_assistant),
) -> ChatResponse:
    return assistant.chat(db, body.message, body.conversation_id)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def reset_conversation(
    conversation_id: str = Path(..., max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    store.delete(conversation_id)
