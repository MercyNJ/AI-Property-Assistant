from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import PROPERTY_TYPES

PropertyType = Literal[PROPERTY_TYPES]
SortBy = Literal["price_asc", "price_desc", "bedrooms_desc", "newest"]


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    location: str
    neighbourhood: str
    county: str
    property_type: str
    bedrooms: int
    bathrooms: int
    price_kes: int
    furnished: bool
    description: str


class PropertySearchFilters(BaseModel):
    """Search filters shared by the REST endpoint and the AI tool."""

    model_config = ConfigDict(extra="forbid")

    location: str | None = Field(None, max_length=80)
    property_type: PropertyType | None = None
    min_bedrooms: int | None = Field(None, ge=0, le=10)
    max_bedrooms: int | None = Field(None, ge=0, le=10)
    min_bathrooms: int | None = Field(None, ge=0, le=10)
    max_price_kes: int | None = Field(None, ge=0, le=10_000_000)
    furnished: bool | None = None
    keywords: str | None = Field(None, max_length=100)
    sort_by: SortBy = "price_asc"
    limit: int = Field(6, ge=1, le=10)

    @model_validator(mode="after")
    def bedroom_range_is_ordered(self) -> "PropertySearchFilters":
        if self.min_bedrooms is not None and self.max_bedrooms is not None and self.min_bedrooms > self.max_bedrooms:
            raise ValueError("min_bedrooms cannot be greater than max_bedrooms.")
        return self


class SearchResult(BaseModel):
    total_matches: int
    criteria_applied: dict
    results: list[PropertyOut]
    relaxation_suggestions: list[dict] = []


class LocationSummary(BaseModel):
    location: str
    county: str
    neighbourhoods: list[str]
    listing_count: int
    min_price_kes: int
    max_price_kes: int
