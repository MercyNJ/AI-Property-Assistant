"""In-memory conversation history behind a get/save/delete interface."""

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Conversation:
    items: list[dict] = field(default_factory=list)  # Responses API input items
    seen_property_ids: set[int] = field(default_factory=set)
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    def __init__(self, max_turns: int = 10, ttl_seconds: int = 6 * 3600, max_conversations: int = 1000):
        self._data: dict[str, Conversation] = {}
        self._lock = threading.Lock()
        self.max_turns = max(1, max_turns)  # a limit of 0 would keep the full history
        self.ttl = ttl_seconds
        self.max_conversations = max_conversations

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def get(self, conversation_id: str) -> Conversation:
        with self._lock:
            self._evict()
            conv = self._data.get(conversation_id)
            if conv is None:
                return Conversation()
            return Conversation(list(conv.items), set(conv.seen_property_ids), conv.updated_at)

    def save(self, conversation_id: str, conv: Conversation) -> None:
        conv.items = self._trim(conv.items)
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
        return items[user_idx[-self.max_turns]:]

    def _evict(self) -> None:
        now = time.time()
        for cid in [c for c, v in self._data.items() if now - v.updated_at > self.ttl]:
            del self._data[cid]
        if len(self._data) > self.max_conversations:
            oldest = sorted(self._data, key=lambda c: self._data[c].updated_at)
            for cid in oldest[: len(self._data) - self.max_conversations]:
                del self._data[cid]
