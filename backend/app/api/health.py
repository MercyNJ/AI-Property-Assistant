from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Property

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        listings = db.scalar(select(func.count(Property.id)))
        db_ok = True
    except SQLAlchemyError:
        listings, db_ok = None, False
        # Render's health check only reads the status code.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    settings = get_settings()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "listings": listings,
        "ai_configured": settings.ai_configured,
        "model": settings.openai_model,
    }
