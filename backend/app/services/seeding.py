import json
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Property


def load_seed_file(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def seed_properties(db: Session, path: Path, reset: bool = False) -> int:
    """Insert listings from the JSON seed file. Skips if the table already has rows (unless reset)."""
    if reset:
        db.execute(delete(Property))
    elif db.scalar(select(func.count(Property.id))):
        return 0

    rows = [
        Property(
            id=item["property_id"],
            title=item["title"],
            location=item["property_location"],
            neighbourhood=item["neighbourhood"],
            county=item["county"],
            property_type=item["property_type"],
            bedrooms=item["bedrooms"],
            bathrooms=item["bathrooms"],
            price_kes=item["price_kes"],
            furnished=item["furnished"],
            description=item["description"],
        )
        for item in load_seed_file(path)
    ]
    db.add_all(rows)
    db.commit()
    return len(rows)
