import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.ai.assistant import AssistantError
from app.api import chat, health, properties
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.services.seeding import seed_properties

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Base.metadata.create_all(engine)
    # Seed an empty database on startup so a fresh deploy needs no manual step.
    if settings.seed_file.exists():
        with SessionLocal() as db:
            added = seed_properties(db, settings.seed_file)
            if added:
                log.info("Seeded %d listings from %s", added, settings.seed_file.name)
    else:
        log.warning("Seed file %s not found: an empty database will stay empty and every search will return 0.",
                    settings.seed_file)
    if not settings.ai_configured:
        log.warning("OPENAI_API_KEY is not set: /api/chat will return 503 until it is configured.")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="BomaTech Property Assistant API", version="1.0.0", lifespan=lifespan)

    # Registered before CORS so 500s keep CORS headers; exception_handler(Exception) runs outside middleware.
    @app.middleware("http")
    async def unhandled_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            log.exception("Unhandled error")
            return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AssistantError)
    async def assistant_error(_: Request, exc: AssistantError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": "The request was invalid.", "errors": errors})

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_: Request, exc: SQLAlchemyError):
        log.exception("Database error", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "The property database is unavailable right now."})

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(properties.router)
    return app


app = create_app()
