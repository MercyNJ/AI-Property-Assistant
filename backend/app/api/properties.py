from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import LocationSummary, PropertyOut, PropertySearchFilters, SearchResult
from app.services import property_service as svc

router = APIRouter(prefix="/api", tags=["properties"])


@router.get("/properties", response_model=SearchResult)
def search(filters: Annotated[PropertySearchFilters, Query()], db: Session = Depends(get_db)) -> SearchResult:
    """Structured search using the same service as the AI tool."""
    return svc.search_properties(db, filters)


@router.get("/properties/{property_id}", response_model=PropertyOut)
def get_one(property_id: int, db: Session = Depends(get_db)) -> PropertyOut:
    try:
        return svc.get_property(db, property_id)
    except svc.PropertyNotFound:
        raise HTTPException(status_code=404, detail=f"Property {property_id} was not found.") from None


@router.get("/locations", response_model=list[LocationSummary])
def locations(q: str | None = Query(None, max_length=80), db: Session = Depends(get_db)) -> list[LocationSummary]:
    return svc.list_locations(db, q)
