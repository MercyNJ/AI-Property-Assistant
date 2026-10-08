import json
import os
import tempfile
from pathlib import Path

# Isolated database and dummy key, set before the app is imported.
_tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["OPENAI_API_KEY"] = "test-key"
# High limits for API tests; test_rate_limit.py installs tight ones where needed.
for _name in ("CHAT_LIMIT_PER_MINUTE", "CHAT_LIMIT_PER_DAY", "CHAT_LIMIT_GLOBAL_PER_DAY"):
    os.environ[_name] = "10000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.assistant import PropertyAssistant  # noqa: E402
from app.ai.conversation_store import ConversationStore  # noqa: E402
from app.api.deps import get_assistant, get_conversation_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.seeding import seed_properties  # noqa: E402


class FakeItem:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none: bool = False):
        return dict(self.__dict__)


class FakeResponse:
    def __init__(self, output, output_text="", status="completed"):
        self.output = output
        self.output_text = output_text
        self.status = status


def function_call(name: str, args: dict, call_id: str = "call_1") -> FakeItem:
    return FakeItem(type="function_call", id=f"fc_{call_id}", call_id=call_id, name=name, arguments=json.dumps(args))


def final(message: str, ids: list[int]) -> FakeResponse:
    text = json.dumps({"message": message, "property_ids": ids})
    return FakeResponse([FakeItem(type="message", role="assistant", content=[])], output_text=text)


class FakeResponses:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(kwargs) if callable(step) else step


class FakeClient:
    def __init__(self, script):
        self.responses = FakeResponses(script)


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_properties(db, get_settings().seed_file, reset=True)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def use_fake_ai():
    """Install a scripted fake model: use_fake_ai([...steps]) -> FakeClient."""

    store = ConversationStore()

    def install(script):
        fake = FakeClient(script)
        assistant = PropertyAssistant(fake, get_settings(), store)
        app.dependency_overrides[get_assistant] = lambda: assistant
        app.dependency_overrides[get_conversation_store] = lambda: store
        return fake

    return install
