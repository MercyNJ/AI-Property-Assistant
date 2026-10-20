# BomaTech: AI Property Assistant

A chat assistant for Kenyan rental listings. Ask in plain language ("furnished 3-bedroom in Ruiru under 80k"). The model turns that into structured tool calls, the backend queries SQLite, and the UI shows the matching listings as cards. Follow-ups such as "Which one is cheapest?" or "Show me only the furnished ones" use the conversation history.

```
React (Vite, TS) ──POST /api/chat──▶ FastAPI ──▶ PropertyAssistant (OpenAI Responses API)
                                                   │  function_call: search_properties {...}
                                                   ▼
                                    tools.run_tool ─▶ property_service ─▶ SQLAlchemy ─▶ SQLite
                                                   │  function_call_output: JSON results
                                                   ▼
                    { reply, properties[], tool_calls[] } ◀── final structured reply {message, property_ids}
```

## Run locally

Prerequisites: Python 3.11+, Node 20.19+ or 22.12+ (required by Vite 8) and an OpenAI API key.

**Backend** (terminal 1):

```bash
cd backend
python -m venv bomatech-venv --prompt bomatech
# Windows: bomatech-venv\Scripts\activate    macOS/Linux: source bomatech-venv/bin/activate
pip install -r requirements-dev.txt
copy ..\.env.example .env            # macOS/Linux: cp ../.env.example .env
# edit backend/.env and set OPENAI_API_KEY
uvicorn app.main:app --reload
```

The API runs at http://localhost:8000, with interactive docs at http://localhost:8000/docs. On first start, the database is created and seeded from `data/properties.json`. To reload the data after editing the JSON, run `python seed.py --reset`.

**Frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
npm run lint        # Oxlint, also run in CI
npm test            # Vitest, also run in CI
```

Open http://localhost:5173. In development, Vite proxies `/api` to the backend, so no CORS setup or frontend env var is needed.

**Tests:**

```bash
cd backend
pytest
ruff check . && ruff format --check .   # lint and formatting, also run in CI
```

The tests replace the OpenAI client with a scripted fake. They need no key and no network, and they cover the tool loop, follow-up history, card ID validation, request validation and error mapping.

## Project layout

```
backend/
  app/
    main.py              app factory, CORS, error handlers, auto-seed on startup
    config.py            settings from environment / .env
    database.py          engine, session, Base
    models/property.py   SQLAlchemy model
    schemas/             Pydantic request/response models (API contract)
    services/            property_service.py: every DB query lives here
    ai/
      prompts.py         system prompt + structured reply schema
      tools.py           tool JSON schemas + validated dispatcher
      assistant.py       Responses API tool-calling loop, error mapping
      conversation_store.py  in-memory history
    api/                 routes: chat, properties, health; deps.py wires the assistant
  seed.py
  tests/
frontend/
  src/
    components/          Header, Welcome, Message, PropertyCard, Composer
    services/api.ts      fetch wrapper with timeout and friendly errors
    types/               TS types mirroring the API schemas
    format.ts            KES formatting, tool-call summaries
data/properties.json     55 sample listings (seed data)
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat` | `{message, conversation_id?}` returns `{conversation_id, reply, properties[], tool_calls[], history_reset}` |
| DELETE | `/api/chat/{id}` | Clear a conversation |
| GET | `/api/properties?location=Ruiru&min_bedrooms=3&max_price_kes=80000` | Structured search; the same service the AI uses |
| GET | `/api/properties/{id}` | One listing (404 if missing) |
| GET | `/api/locations?q=` | Supported locations, counts and rent ranges |
| GET | `/api/health` | DB status, listing count, whether AI is configured |

## Key design decisions

**The LLM never touches the database.** It can only call four named tools: `search_properties`, `get_property`, `compare_properties` and `search_locations`. Their JSON schemas use strict mode, so arguments always match the schema. They are validated again with Pydantic before reaching `property_service`, and the service builds parameterised SQLAlchemy queries. No model-generated SQL runs anywhere.

**Tool errors go back to the model as data.** An invalid argument or unknown ID becomes `{"error": "..."}` in the tool output, so the model can recover or explain the problem. It never surfaces as a 500.

**Structured final reply.** The model's last message is JSON `{message, property_ids}`, enforced by `text.format` with a strict JSON schema. The backend displays only cards whose IDs a tool actually returned in the retained conversation history, and loads them from the database, so an invented listing can't reach the screen.

**No-match handling is computed, not guessed.** When a search returns nothing, the service counts how many listings would match with each single criterion removed. For the budget, it also reports the lowest matching price. The model uses those numbers to suggest relaxing one criterion.

**Conversation history.** Kept server-side in memory per `conversation_id`, as Responses API input items: user messages, compact `function_call` and `function_call_output` pairs, and assistant replies. History is trimmed at user-turn boundaries so calls stay paired with their outputs. Because past tool results stay in context, "Which one is cheapest?" needs no new query. History is held in process memory, so a restart clears it. `ConversationStore` exposes a three-method interface (get, save, delete), so a persistent backend can replace it without changes to the assistant. A conversation runs one turn at a time; an overlapping request gets a 409 instead of overwriting the turn in progress.

**Structured filtering before embeddings.** Every user criterion here (location, type, bedrooms, budget, furnished) is a structured column, and SQL filters are exact, explainable and fast. Feature words like "pool" or "borehole" use a `keywords` match on descriptions. Embeddings would add value for fuzzy intent ("quiet, near good schools") once descriptions are richer. That would be a new `semantic_search` tool, or a re-rank step inside `property_service`, with the vectors in pgvector after the move to Postgres. Nothing else would need to change.

**Objective language.** Listings store only objective facts. The prompt forbids "cheap" or "affordable" and asks for relative statements instead, for example "KES 28,000 below your budget".

**Errors.** OpenAI failures are mapped to user-safe messages and status codes: auth or permission 503, rate limit 429, timeout 504, connection 503, model not found 503. Database errors return 503, validation errors return 422 with field messages, and anything else returns a generic 500. Details are logged server-side. Responses never contain stack traces or keys. A missing `OPENAI_API_KEY` doesn't stop the server; `/api/chat` explains what to set.

**Rate limiting.** `/api/chat` spends OpenAI credit, so it is limited to 10 messages per minute and 100 per day per IP, plus 1,000 per day overall. The overall cap is a hard ceiling on spend. All three are configurable (`CHAT_LIMIT_*`). Over the limit, the API returns 429 with a friendly message. The counters are in memory, so they reset on restart.

**Security.** The API key lives only in the backend environment. React talks only to FastAPI. `.env` is gitignored. Request bodies are validated: message 1–1000 characters, and `conversation_id` must match `[A-Za-z0-9_-]{1,64}`. CORS is restricted to the configured origins.

## Deployment

**Backend on Render.** Create a Blueprint from `render.yaml`, or a Web Service with root `backend`, build command `pip install -r requirements.txt` and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT --forwarded-allow-ips="*"` (this lets the chat rate limit see each visitor's IP). Set `OPENAI_API_KEY`, and set `CORS_ORIGINS` to your Vercel URL. SQLite works on Render's ephemeral disk because the read-only listings are re-seeded from `data/properties.json` on every start. Once listings are written at runtime, switch `DATABASE_URL` to Render Postgres.

**Frontend on Vercel.** Import the repo with root directory `frontend`. The framework is detected as Vite. Set `VITE_API_URL=https://<your-render-service>.onrender.com`.

## Configuration

See `.env.example`. `OPENAI_MODEL` defaults to `gpt-5.4-mini`. Any Responses API model with function calling and structured outputs works. For non-reasoning models such as `gpt-4.1-mini`, set `OPENAI_REASONING_EFFORT=` (empty).

## Extending it

- **Postgres/PostGIS:** change `DATABASE_URL` and add `psycopg`. Then add lat/lng columns, and a `near` filter in `property_service`.
- **Images and maps:** add a `property_images` table and a `PropertyOut.images` field, and render them in the cards.
- **Auth, agents and listings management:** add users and agents tables, plus authenticated CRUD routes that reuse the same service layer.
- **Semantic search and recommendations:** see the embeddings note above. User preferences can become default filters that are injected into the tool arguments.
- **Persistence:** a Redis or DB-backed `ConversationStore`.
- **M-Pesa, notifications and admin:** separate services and routers. None of them change the assistant.

## Future improvements

- **Evaluation set.** A fixed list of test requests with the listings each should return, run against the real model after every prompt change. Each run is scored on whether wrong listings were shown and whether correct ones were missed, so a fix that breaks something else is caught.
