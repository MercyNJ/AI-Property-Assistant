"""In-memory conversation history behind a get/save/delete interface."""

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


class ConversationBusy(Exception):
    """Another request is already running a turn for this conversation."""


@dataclass
class Conversation:
    items: list[dict] = field(default_factory=list)  # Responses API input items
    # Listing IDs surfaced by tools, one list per user turn in `items`, trimmed with it.
    turn_property_ids: list[list[int]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    @property
    def seen_property_ids(self) -> set[int]:
        return {pid for ids in self.turn_property_ids for pid in ids}


class ConversationStore:
    def __init__(self, max_turns: int = 10, ttl_seconds: int = 6 * 3600, max_conversations: int = 1000):
        self._data: dict[str, Conversation] = {}
        self._busy: set[str] = set()
        self._lock = threading.Lock()
        self.max_turns = max(1, max_turns)  # a limit of 0 would keep the full history
        self.ttl = ttl_seconds
        self.max_conversations = max_conversations

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    @contextmanager
    def turn(self, conversation_id: str) -> Iterator[None]:
        """Hold the conversation for one get/save cycle; raises ConversationBusy if already held."""
        with self._lock:
            if conversation_id in self._busy:
                raise ConversationBusy(conversation_id)
            self._busy.add(conversation_id)
        try:
            yield
        finally:
            with self._lock:
                self._busy.discard(conversation_id)

    def get(self, conversation_id: str) -> Conversation:
        with self._lock:
            self._evict()
            conv = self._data.get(conversation_id)
            if conv is None:
                return Conversation()
            return Conversation(list(conv.items), [list(ids) for ids in conv.turn_property_ids], conv.updated_at)

    def save(self, conversation_id: str, conv: Conversation) -> None:
        conv.items = self._trim(conv.items)
        user_turns = sum(1 for it in conv.items if it.get("role") == "user")
        conv.turn_property_ids = conv.turn_property_ids[-user_turns:] if user_turns else []
        conv.updated_at = time.time()
        with self._lock:
            self._data[conversation_id] = conv
            self._evict()

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._data.pop(conversation_id, None)

    def _trim(self, items: list[dict]) -> list[dict]:
        """Keep the last N user turns, cutting only at user messages so tool calls stay paired."""
        user_idx = [i for i, it in enumerate(items) if it.get("role") == "user"]
        if len(user_idx) <= self.max_turns:
            return items
        return items[user_idx[-self.max_turns] :]

    def _evict(self) -> None:
        now = time.time()
        for cid in [c for c, v in self._data.items() if now - v.updated_at > self.ttl]:
            del self._data[cid]
        if len(self._data) > self.max_conversations:
            oldest = sorted(self._data, key=lambda c: self._data[c].updated_at)
            for cid in oldest[: len(self._data) - self.max_conversations]:
                del self._data[cid]
