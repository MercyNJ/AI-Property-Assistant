"""OpenAI Responses API tool-calling loop over the property tools."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import openai
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.conversation_store import ConversationBusy, ConversationStore
from app.ai.prompts import REPLY_SCHEMA, SYSTEM_PROMPT
from app.ai.tools import TOOLS, run_tool
from app.config import Settings
from app.schemas import ChatResponse, ToolCallInfo
from app.services import property_service as svc

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
# Whole-turn budget in seconds; must stay below the frontend's TIMEOUT_MS so a turn never outlives the request.
TURN_BUDGET_SECONDS = 50
MIN_CALL_SECONDS = 3


class AssistantError(Exception):
    """An error that is safe to show to the user."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AssistantReply(BaseModel):
    message: str
    property_ids: list[int] = []


@dataclass
class _Turn:
    new_items: list[dict] = field(default_factory=list)  # persisted to history
    tool_calls: list[ToolCallInfo] = field(default_factory=list)
    surfaced_ids: list[int] = field(default_factory=list)
    deadline: float = 0.0


def _as_dict(item) -> dict:
    return item if isinstance(item, dict) else item.model_dump(exclude_none=True)


class PropertyAssistant:
    def __init__(
        self, client, settings: Settings, store: ConversationStore, clock: Callable[[], float] = time.monotonic
    ):
        self.client = client
        self.settings = settings
        self.store = store
        self.clock = clock

    def chat(self, db: Session, message: str, conversation_id: str | None) -> ChatResponse:
        resuming = conversation_id is not None
        conversation_id = conversation_id or self.store.new_id()
        try:
            with self.store.turn(conversation_id):
                return self._chat_turn(db, message, conversation_id, resuming)
        except ConversationBusy:
            raise AssistantError("Still answering your previous message. Please wait for it to finish.", 409) from None

    def _chat_turn(self, db: Session, message: str, conversation_id: str, resuming: bool) -> ChatResponse:
        conv = self.store.get(conversation_id)
        # A known ID with no stored history means it expired or the server restarted.
        history_reset = resuming and not conv.items
        turn = _Turn(new_items=[{"role": "user", "content": message}], deadline=self.clock() + TURN_BUDGET_SECONDS)

        try:
            reply = self._run(db, conv.items, turn)
        except openai.APIError as exc:
            raise self._map_openai_error(exc) from exc
        except SQLAlchemyError as exc:
            log.exception("Database error during chat")
            raise AssistantError(
                "The property database is unavailable right now. Please try again shortly.", 503
            ) from exc

        # Cards only for listings a tool returned in the retained history, so invented IDs never render.
        conv.turn_property_ids.append(list(dict.fromkeys(turn.surfaced_ids)))
        allowed = [pid for pid in dict.fromkeys(reply.property_ids) if pid in conv.seen_property_ids]
        properties = svc.get_properties_by_ids(db, allowed)

        turn.new_items.append({"role": "assistant", "content": reply.model_dump_json()})
        conv.items.extend(turn.new_items)
        self.store.save(conversation_id, conv)

        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply.message,
            properties=properties,
            tool_calls=turn.tool_calls,
            history_reset=history_reset,
        )

    def _run(self, db: Session, history: list[dict], turn: _Turn) -> AssistantReply:
        # Reasoning items stay in the input for this turn only; turn.new_items holds what is persisted.
        working: list[dict] = list(history) + list(turn.new_items)

        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = self._create(working, turn.deadline)
            calls = [item for item in response.output if item.type == "function_call"]

            if not calls:
                return self._parse_reply(response)

            working.extend(_as_dict(item) for item in response.output)
            for call in calls:
                result = run_tool(db, call.name, call.arguments)
                output_item = {"type": "function_call_output", "call_id": call.call_id, "output": result.output}
                working.append(output_item)

                turn.new_items.append(
                    {"type": "function_call", "call_id": call.call_id, "name": call.name, "arguments": call.arguments}
                )
                turn.new_items.append(output_item)
                turn.surfaced_ids.extend(result.property_ids)
                turn.tool_calls.append(ToolCallInfo(name=call.name, arguments=_safe_json(call.arguments)))

        raise AssistantError("The assistant could not complete that request. Please try rephrasing it.", 502)

    def _create(self, input_items: list[dict], deadline: float):
        kwargs = dict(
            model=self.settings.openai_model,
            instructions=SYSTEM_PROMPT,
            input=input_items,
            tools=TOOLS,
            text={"format": REPLY_SCHEMA},
            parallel_tool_calls=True,
            max_output_tokens=2000,
        )
        if self.settings.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.settings.reasoning_effort}

        # SDK retries are off (deps.py) because they can sleep past the budget; retry transient failures here.
        for attempt in range(2):
            remaining = deadline - self.clock()
            if remaining < MIN_CALL_SECONDS:
                raise AssistantError("The assistant took too long to answer. Please try again.", 504)
            try:
                return self.client.responses.create(**kwargs, timeout=min(self.settings.openai_timeout, remaining))
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                if attempt:
                    raise
                log.warning("Retrying OpenAI call after %s", type(exc).__name__)

    @staticmethod
    def _parse_reply(response) -> AssistantReply:
        text = (getattr(response, "output_text", "") or "").strip()
        if not text:
            # A refusal arrives as a "refusal" content part with an empty output_text.
            if refusal := _refusal_text(response):
                return AssistantReply(message=refusal, property_ids=[])
            if getattr(response, "status", None) == "incomplete":
                raise AssistantError("The assistant's reply was cut short. Please try a more specific question.", 502)
            raise AssistantError("The assistant returned an empty reply. Please try again.", 502)
        try:
            return AssistantReply.model_validate_json(text)
        except ValidationError:
            # Not expected with strict output; show the raw text without cards.
            log.warning("Reply did not match schema: %.200s", text)
            return AssistantReply(message=text, property_ids=[])

    @staticmethod
    def _map_openai_error(exc: openai.APIError) -> AssistantError:
        log.error("OpenAI error: %s: %s", type(exc).__name__, exc)
        if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            return AssistantError(
                "The AI service rejected the server's credentials. Check OPENAI_API_KEY on the backend.", 503
            )
        if isinstance(exc, openai.RateLimitError):
            return AssistantError(
                "The AI service is busy or the usage quota has been reached. Please try again in a moment.", 429
            )
        if isinstance(exc, openai.APITimeoutError):
            return AssistantError("The AI service took too long to respond. Please try again.", 504)
        if isinstance(exc, openai.APIConnectionError):
            return AssistantError("Could not reach the AI service. Please try again shortly.", 503)
        if isinstance(exc, openai.NotFoundError):
            return AssistantError("The configured AI model is not available. Check OPENAI_MODEL on the backend.", 503)
        return AssistantError("The AI service returned an error. Please try again.", 502)


def _refusal_text(response) -> str:
    parts = [
        part.refusal
        for item in response.output
        if item.type == "message"
        for part in getattr(item, "content", [])
        if part.type == "refusal"
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())


def _safe_json(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
        return {k: v for k, v in value.items() if v is not None} if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}
