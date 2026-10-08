from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PROPERTY_TYPES = ("apartment", "studio", "bedsitter", "townhouse", "maisonette", "bungalow")


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(80), index=True)
    neighbourhood: Mapped[str] = mapped_column(String(80))
    county: Mapped[str] = mapped_column(String(80), index=True)
    property_type: Mapped[str] = mapped_column(String(30), index=True)
    bedrooms: Mapped[int] = mapped_column(Integer, index=True)
    bathrooms: Mapped[int] = mapped_column(Integer)
    price_kes: Mapped[int] = mapped_column(Integer, index=True)  # monthly rent
    furnished: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
