"""Tool schemas exposed to the model and the dispatcher that validates and runs them."""

import json
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.models import PROPERTY_TYPES
from app.schemas import PropertySearchFilters
from app.services import property_service as svc


def _nullable(schema: dict) -> dict:
    out = dict(schema)
    out["type"] = [schema["type"], "null"]
    if "enum" in out:
        out["enum"] = [*out["enum"], None]
    return out


# Strict mode: every property is required; optional ones are nullable.
TOOLS: list[dict] = [
    {
        "type": "function",
        "name": "search_properties",
        "description": (
            "Search rental listings with structured filters. Use null for any filter the user did not specify. "
            "Returns total_matches, the applied criteria, up to `limit` listings and, when nothing matches, "
            "relaxation_suggestions."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "location": _nullable({"type": "string", "description": "One place name: a town, neighbourhood or county, e.g. 'Ruiru', 'Kamakis', 'Nairobi'. Do not add the county or country."}),
                "property_type": _nullable({"type": "string", "enum": list(PROPERTY_TYPES)}),
                "min_bedrooms": _nullable({"type": "integer", "description": "For an exact count ('3-bedroom') set min and max to the same number. Studios and bedsitters have 0 bedrooms."}),
                "max_bedrooms": _nullable({"type": "integer", "description": "Equal to min_bedrooms for an exact count; alone only for 'up to N'."}),
                "min_bathrooms": _nullable({"type": "integer"}),
                "max_price_kes": _nullable({"type": "integer", "description": "Maximum monthly rent in KES."}),
                "furnished": _nullable({"type": "boolean"}),
                "keywords": _nullable({"type": "string", "description": "Short feature words that must all appear in the listing, e.g. 'pool', 'gym borehole', 'DSQ'. Use the core noun ('pool', not 'swimming pool'); no descriptive or filler words."}),
                "sort_by": {"type": "string", "enum": ["price_asc", "price_desc", "bedrooms_desc", "newest"]},
                "limit": _nullable({"type": "integer", "description": "1-10, default 6."}),
            },
            "required": [
                "location", "property_type", "min_bedrooms", "max_bedrooms", "min_bathrooms",
                "max_price_kes", "furnished", "keywords", "sort_by", "limit",
            ],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_property",
        "description": "Get full details of one listing by its ID.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"property_id": {"type": "integer"}},
            "required": ["property_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "compare_properties",
        "description": "Compare 2-5 listings by ID on objective attributes (price, bedrooms, bathrooms, furnished, price per bedroom).",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"property_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["property_ids"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_locations",
        "description": "List supported locations with listing counts and rent ranges. Pass null to list all, or text to filter.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"query": _nullable({"type": "string"})},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


class _GetPropertyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: int = Field(..., ge=1)


class _CompareArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_ids: list[int] = Field(..., min_length=2, max_length=5)


class _LocationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(None, max_length=80)


@dataclass
class ToolResult:
    output: str  # JSON string sent back to the model
    property_ids: list[int] = field(default_factory=list)  # listings the tool surfaced


def _error(message: str) -> ToolResult:
    return ToolResult(json.dumps({"error": message}))


def run_tool(db: Session, name: str, raw_arguments: str) -> ToolResult:
    """Run a tool call; errors are returned to the model as data."""
    try:
        args = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return _error("Arguments were not valid JSON.")
    if not isinstance(args, dict):
        return _error("Arguments must be a JSON object.")

    try:
        if name == "search_properties":
            args = {k: v for k, v in args.items() if v is not None}
            if isinstance(args.get("limit"), int):
                args["limit"] = min(max(args["limit"], 1), 10)
            filters = PropertySearchFilters(**args)
            result = svc.search_properties(db, filters)
            return ToolResult(result.model_dump_json(), [p.id for p in result.results])

        if name == "get_property":
            a = _GetPropertyArgs(**args)
            try:
                prop = svc.get_property(db, a.property_id)
            except svc.PropertyNotFound as exc:
                return _error(str(exc))
            return ToolResult(prop.model_dump_json(), [prop.id])

        if name == "compare_properties":
            a = _CompareArgs(**args)
            result = svc.compare_properties(db, a.property_ids)
            return ToolResult(json.dumps(result), [p["id"] for p in result["properties"]])

        if name == "search_locations":
            a = _LocationArgs(**args)
            locations = svc.list_locations(db, a.query)
            return ToolResult(json.dumps({"locations": [loc.model_dump() for loc in locations]}))

    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return _error(f"Invalid arguments: {details}")

    return _error(f"Unknown tool '{name}'.")
