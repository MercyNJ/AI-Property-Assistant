"""All property database queries; the AI layer reaches them only through tools."""

import re

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import Property
from app.schemas import LocationSummary, PropertyOut, PropertySearchFilters, SearchResult

# Common alternative spellings mapped to the stored value.
LOCATION_ALIASES = {
    "kiambu road": "thindigua",
    "tatu": "tatu city",
    "sports view": "sportsview",
    "thika town": "thika",
    "nairobi city": "nairobi",
    "nbi": "nairobi",
}

# Feature phrases (in _stem form) mapped to the wording used in listings.
KEYWORD_ALIASES = {
    "swimming pool": "pool",
    "parking space": "parking",
    "servant quarter": "dsq",
    "wifi": "wi-fi",
    "fiber": "fibre",
}
KEYWORD_STOP_WORDS = {"a", "an", "and", "the", "with", "has", "have", "of", "or"}

FILTER_FIELDS = (
    "location", "property_type", "min_bedrooms", "max_bedrooms",
    "min_bathrooms", "max_price_kes", "furnished", "keywords",
)


class PropertyNotFound(Exception):
    def __init__(self, property_id: int):
        super().__init__(f"Property {property_id} does not exist.")
        self.property_id = property_id


def _plain(raw: str) -> str:
    return " ".join(raw.lower().replace(",", " ").split())


def _normalise_location(raw: str) -> str:
    key = _plain(raw)
    for suffix in (" kenya", " county"):
        key = key.removesuffix(suffix)
    return LOCATION_ALIASES.get(key, key)


def _location_candidates(raw: str) -> list[str]:
    """Keys to try, most specific first; the exact phrase comes before aliases so a stored name always wins."""
    keys: list[str] = []
    for part in (raw, raw.split(",")[0]):
        key = _normalise_location(part)
        keys += [_plain(part), key]
        for filler in (" area", " town"):
            if key.endswith(filler):
                keys.append(_normalise_location(key.removesuffix(filler)))
    return list(dict.fromkeys(keys))


def resolve_location(db: Session, raw: str) -> str | None:
    """Stored location, county or neighbourhood name the user meant (most specific wins), or None."""
    names: dict[str, str] = {}
    for row in db.execute(select(Property.location, Property.county, Property.neighbourhood).distinct()):
        for name in row:
            names.setdefault(name.lower(), name)
    return next((names[k] for k in _location_candidates(raw) if k in names), None)


def _location_match(name: str):
    # `name` is already resolved by search_properties; unresolved input matches nothing either way.
    key = name.lower()
    return or_(
        func.lower(Property.location) == key,
        func.lower(Property.county) == key,
        func.lower(Property.neighbourhood) == key,
    )


def _contains(text: str) -> str:
    """ILIKE pattern matching `text` literally anywhere; use with escape="\\"."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _stem(word: str) -> str:
    """A form that is a substring of both singular and plural: "pools" -> pool, "balconies" -> balcon."""
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    # Consonant + "y" pluralises to "-ies"; short words keep the "y" so "study" doesn't match "studio".
    if len(word) > 5 and word.endswith("y") and word[-2] not in "aeiou":
        word = word[:-1]
    return word


def _keyword_terms(keywords: str) -> list[str]:
    text = " ".join(_stem(w) for w in keywords.lower().replace(",", " ").replace("'", "").split())
    for phrase, replacement in KEYWORD_ALIASES.items():
        text = re.sub(rf"\b{re.escape(phrase)}\b", replacement, text)
    terms = [w for w in text.split() if w not in KEYWORD_STOP_WORDS]
    return list(dict.fromkeys(terms))[:5]


def _apply_filters(stmt: Select, f: PropertySearchFilters) -> Select:
    if f.location:
        stmt = stmt.where(_location_match(f.location))
    if f.property_type:
        stmt = stmt.where(Property.property_type == f.property_type)
    if f.min_bedrooms is not None:
        stmt = stmt.where(Property.bedrooms >= f.min_bedrooms)
    if f.max_bedrooms is not None:
        stmt = stmt.where(Property.bedrooms <= f.max_bedrooms)
    if f.min_bathrooms is not None:
        stmt = stmt.where(Property.bathrooms >= f.min_bathrooms)
    if f.max_price_kes is not None:
        stmt = stmt.where(Property.price_kes <= f.max_price_kes)
    if f.furnished is not None:
        stmt = stmt.where(Property.furnished.is_(f.furnished))
    if f.keywords:
        # Every term must appear in the title or description.
        for word in _keyword_terms(f.keywords):
            pattern = _contains(word)
            stmt = stmt.where(or_(Property.title.ilike(pattern, escape="\\"),
                                  Property.description.ilike(pattern, escape="\\")))
    return stmt


def _count(db: Session, f: PropertySearchFilters) -> int:
    return db.scalar(_apply_filters(select(func.count(Property.id)), f)) or 0


def _criteria(f: PropertySearchFilters) -> dict:
    return {k: v for k, v in f.model_dump().items() if k in FILTER_FIELDS and v is not None}


def search_properties(db: Session, f: PropertySearchFilters) -> SearchResult:
    location_known = True
    if f.location:
        resolved = resolve_location(db, f.location)
        location_known = resolved is not None
        if resolved:
            f = f.model_copy(update={"location": resolved})

    order = {
        "price_asc": (Property.price_kes.asc(), Property.id),
        "price_desc": (Property.price_kes.desc(), Property.id),
        "bedrooms_desc": (Property.bedrooms.desc(), Property.price_kes.asc()),
        "newest": (Property.created_at.desc(), Property.id.desc()),
    }[f.sort_by]

    total = _count(db, f)
    rows = db.scalars(_apply_filters(select(Property), f).order_by(*order).limit(f.limit)).all()

    suggestions: list[dict] = []
    if total == 0:
        suggestions = _relaxation_suggestions(db, f, location_known)

    return SearchResult(
        total_matches=total,
        criteria_applied=_criteria(f),
        results=[PropertyOut.model_validate(r) for r in rows],
        relaxation_suggestions=suggestions,
    )


def _relaxation_suggestions(db: Session, f: PropertySearchFilters, location_known: bool) -> list[dict]:
    """For a zero-result search, count the matches with each single criterion removed."""
    out: list[dict] = []
    for field in _criteria(f):
        relaxed = f.model_copy(update={field: None})
        n = _count(db, relaxed)
        if n == 0:
            continue
        item: dict = {"remove_criterion": field, "matches_if_removed": n}
        if field == "max_price_kes":
            item["lowest_matching_price_kes"] = db.scalar(
                _apply_filters(select(func.min(Property.price_kes)), relaxed)
            )
        out.append(item)
    if f.location and not location_known:
        out.insert(0, {"note": f"'{f.location}' is not a location in the listings database."})
    return out


def get_property(db: Session, property_id: int) -> PropertyOut:
    row = db.get(Property, property_id)
    if row is None:
        raise PropertyNotFound(property_id)
    return PropertyOut.model_validate(row)


def get_properties_by_ids(db: Session, ids: list[int]) -> list[PropertyOut]:
    if not ids:
        return []
    rows = {r.id: r for r in db.scalars(select(Property).where(Property.id.in_(ids))).all()}
    return [PropertyOut.model_validate(rows[i]) for i in ids if i in rows]


def compare_properties(db: Session, ids: list[int]) -> dict:
    found = get_properties_by_ids(db, list(dict.fromkeys(ids)))
    missing = [i for i in dict.fromkeys(ids) if i not in {p.id for p in found}]
    if len(found) < 2:
        return {"properties": [p.model_dump() for p in found], "missing_ids": missing,
                "error": "At least two existing properties are needed for a comparison."}

    with_beds = [p for p in found if p.bedrooms > 0]
    return {
        "properties": [p.model_dump() for p in found],
        "missing_ids": missing,
        "summary": {
            "lowest_price_id": min(found, key=lambda p: p.price_kes).id,
            "highest_price_id": max(found, key=lambda p: p.price_kes).id,
            "price_difference_kes": max(p.price_kes for p in found) - min(p.price_kes for p in found),
            "most_bedrooms_id": max(found, key=lambda p: (p.bedrooms, -p.price_kes)).id,
            "most_bathrooms_id": max(found, key=lambda p: (p.bathrooms, -p.price_kes)).id,
            "lowest_price_per_bedroom": (
                min(
                    ({"id": p.id, "kes_per_bedroom": round(p.price_kes / p.bedrooms)} for p in with_beds),
                    key=lambda x: x["kes_per_bedroom"],
                )
                if with_beds else None
            ),
            "furnished_ids": [p.id for p in found if p.furnished],
        },
    }


def list_locations(db: Session, query: str | None = None) -> list[LocationSummary]:
    stmt = select(
        Property.location,
        Property.county,
        func.count(Property.id),
        func.min(Property.price_kes),
        func.max(Property.price_kes),
    ).group_by(Property.location, Property.county).order_by(Property.location)

    if query:
        # Match locations first so counts and rent ranges cover all of their listings.
        pattern = _contains(query.strip())
        matching = select(Property.location).where(
            or_(Property.location.ilike(pattern, escape="\\"), Property.county.ilike(pattern, escape="\\"),
                Property.neighbourhood.ilike(pattern, escape="\\"))
        )
        stmt = stmt.where(Property.location.in_(matching))

    hoods: dict[str, set[str]] = {}
    for loc, hood in db.execute(select(Property.location, Property.neighbourhood)).all():
        hoods.setdefault(loc, set()).add(hood)

    return [
        LocationSummary(location=loc, county=county, neighbourhoods=sorted(hoods.get(loc, ())),
                        listing_count=n, min_price_kes=lo, max_price_kes=hi)
        for loc, county, n, lo, hi in db.execute(stmt).all()
    ]
