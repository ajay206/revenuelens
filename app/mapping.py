"""Schema mapping for RevenueLens."""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.discovery import SchemaProfile
    from app.llm import LLM

logger = logging.getLogger(__name__)


CANONICAL: dict[str, list[str]] = {
    "customer": [
        "customer_id",
        "name",
        "type",
        "created",
        "status",
    ],
    "plan": [
        "plan_id",
        "description",
        "monthly_fee",
        "included_data",
        "overage_rate",
        "included_voice",
        "voice_rate",
        "valid_from",
        "valid_to",
    ],
    "rate": [
        "rate_id",
        "plan_id",
        "usage_type",
        "unit_rate",
        "valid_from",
        "valid_to",
    ],
    "discount": [
        "discount_id",
        "description",
        "percent",
        "valid_from",
        "valid_to",
    ],
    "contract": [
        "contract_id",
        "customer_id",
        "plan_id",
        "agreed_fee",
        "discount_id",
        "start",
        "end",
        "auto_renew",
    ],
    "subscription": [
        "subscription_id",
        "customer_id",
        "msisdn",
        "plan_id",
        "activated",
        "deactivated",
        "status",
        "billing_account",
    ],
    "subscription_discount": [
        "subscription_id",
        "discount_id",
        "applied_from",
        "applied_to",
    ],
    "usage": [
        "usage_id",
        "subscription_id",
        "usage_type",
        "timestamp",
        "quantity",
        "rated_flag",
    ],
    "rated_event": [
        "rated_id",
        "usage_id",
        "subscription_id",
        "period",
        "amount",
        "invoiced_flag",
    ],
    "invoice": [
        "invoice_id",
        "billing_account",
        "customer_id",
        "period",
        "invoice_date",
        "total",
        "due_date",
    ],
    "invoice_line": [
        "invoice_id",
        "line_no",
        "subscription_id",
        "charge_type",
        "charge_ref",
        "amount",
    ],
    "payment": [
        "payment_id",
        "customer_id",
        "invoice_id",
        "payment_date",
        "amount",
        "channel",
    ],
    "renewal": [
        "renewal_id",
        "contract_id",
        "due_date",
        "status",
        "new_end",
    ],
}

# Abbreviation expansion mapping
ABBREV_MAP = {
    "cust": "customer",
    "nm": "name",
    "typ": "type",
    "amt": "amount",
    "tot": "total",
    "prd": "period",
    "dt": "date",
    "pln": "plan",
    "disc": "discount",
    "subscr": "subscription",
    "inv": "invoice",
    "hdr": "header",
    "dtl": "line",
    "ln": "line",
    "chg": "charge",
    "ref": "reference",
    "pymt": "payment",
    "rnw": "renewal",
    "renew": "renewal",
    "usg": "usage",
    "cdr": "usage",
    "rtd": "rated",
    "trf": "rate",
    "rt": "rate",
    "cntr": "contract",
    "contract": "contract",
    "mthly": "monthly",
    "incl": "included",
    "ovg": "overage",
    "eff": "effective",
    "act": "activated",
    "deact": "deactivated",
    "stat": "status",
    "flg": "flag",
    "qty": "quantity",
    "evt": "event",
    "ts": "timestamp",
    "chnl": "channel",
    "acct": "account",
}


def expand_token(token: str) -> str:
    """Expand abbreviated token to full form."""
    return ABBREV_MAP.get(token.lower(), token.lower())


def tokenize(name: str) -> set[str]:
    """Split name into tokens and expand abbreviations."""
    return {expand_token(t) for t in name.split("_")}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Calculate Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


@dataclass
class FieldMap:
    """Mapping of a canonical field to a physical column."""

    entity: str
    field: str
    table: str
    column: str
    confidence: float
    source: str  # "heuristic" | "llm" | "human"


@dataclass
class Mapping:
    """Complete schema mapping."""

    entities: dict[str, str]  # entity -> table
    fields: list[FieldMap]
    status: str = "proposed"
    approved_by: str | None = None

    def table(self, entity: str) -> str | None:
        """Get table name for entity."""
        return self.entities.get(entity)

    def column(self, entity: str, field: str) -> str | None:
        """Get column name for entity field."""
        for fm in self.fields:
            if fm.entity == entity and fm.field == field:
                return fm.column
        return None

    def approve(self, user: str) -> None:
        """Mark mapping as approved."""
        self.status = "approved"
        self.approved_by = user

    def correct(self, entity: str, field: str, column: str) -> None:
        """Correct a field mapping with human-verified column."""
        for fm in self.fields:
            if fm.entity == entity and fm.field == field:
                fm.column = column
                fm.confidence = 1.0
                fm.source = "human"
                return
        # If not found, add new
        table = self.entities.get(entity)
        if table:
            self.fields.append(
                FieldMap(
                    entity=entity,
                    field=field,
                    table=table,
                    column=column,
                    confidence=1.0,
                    source="human",
                )
            )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "entities": self.entities,
            "fields": [dataclasses.asdict(fm) for fm in self.fields],
            "status": self.status,
            "approved_by": self.approved_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Mapping:
        """Create Mapping from dictionary."""
        fields = [FieldMap(**fm) for fm in data.get("fields", [])]
        return cls(
            entities=data.get("entities", {}),
            fields=fields,
            status=data.get("status", "proposed"),
            approved_by=data.get("approved_by"),
        )


def heuristic_map(profile: SchemaProfile) -> Mapping:
    """Generate mapping using heuristic rules."""
    entities: dict[str, str] = {}
    tables_sorted = sorted(profile.tables.keys())

    for table in tables_sorted:
        tokens = set(table.split("_"))
        entity = None
        if tokens & {"hdr", "header"}:
            entity = "invoice"
        elif tokens & {"dtl", "line"}:
            entity = "invoice_line"
        elif "rtd" in tokens:
            entity = "rated_event"
        elif tokens & {"cdr", "usg"}:
            entity = "usage"
        elif "trf" in tokens or "rate" in tokens:
            entity = "rate"
        elif "plan" in tokens:
            entity = "plan"
        elif "subscr" in tokens and "disc" in tokens:
            entity = "subscription_discount"
        elif "subscr" in tokens:
            entity = "subscription"
        elif "disc" in tokens:
            entity = "discount"
        elif tokens & {"cntr", "contract"}:
            entity = "contract"
        elif "cust" in tokens:
            entity = "customer"
        elif tokens & {"pymt", "payment"}:
            entity = "payment"
        elif tokens & {"rnw", "renew"}:
            entity = "renewal"

        if entity and entity not in entities:
            entities[entity] = table

    fields: list[FieldMap] = []

    for entity, table in entities.items():
        canonical_fields = CANONICAL.get(entity, [])
        table_profile = profile.tables.get(table)
        if not table_profile:
            continue

        table_columns = [c.name for c in table_profile.columns]

        if len(table_columns) == len(canonical_fields):
            # Positional mapping
            for i, field in enumerate(canonical_fields):
                fields.append(
                    FieldMap(
                        entity=entity,
                        field=field,
                        table=table,
                        column=table_columns[i],
                        confidence=0.9,
                        source="heuristic",
                    )
                )
        else:
            # Token similarity mapping
            for field in canonical_fields:
                field_tokens = tokenize(field)
                best_col = None
                best_score = 0.0
                for col in table_columns:
                    col_tokens = tokenize(col)
                    score = jaccard_similarity(field_tokens, col_tokens)
                    if score > best_score:
                        best_score = score
                        best_col = col
                if best_col:
                    fields.append(
                        FieldMap(
                            entity=entity,
                            field=field,
                            table=table,
                            column=best_col,
                            confidence=best_score,
                            source="heuristic",
                        )
                    )

    return Mapping(entities=entities, fields=fields)


def llm_refine(mapping: Mapping, profile: SchemaProfile, llm: LLM) -> Mapping:
    """Refine mapping using LLM suggestions for low-confidence fields."""
    # Build context
    tables_info = {}
    for entity, table in mapping.entities.items():
        table_profile = profile.tables.get(table)
        if not table_profile:
            continue
        cols = []
        for col_profile in table_profile.columns:
            cols.append(
                {
                    "name": col_profile.name,
                    "samples": col_profile.samples[:3],
                }
            )
        tables_info[table] = {
            "columns": cols,
        }

    # Find fields with confidence < 0.7
    low_confidence = [
        fm for fm in mapping.fields if fm.confidence < 0.7
    ]

    if not low_confidence:
        return mapping

    # Build prompt
    prompt = {
        "tables": tables_info,
        "current_mapping": [
            {
                "entity": fm.entity,
                "field": fm.field,
                "table": fm.table,
                "column": fm.column,
                "confidence": fm.confidence,
            }
            for fm in low_confidence
        ],
    }

    system = (
        "You are a database schema mapper. Given table schemas and current field mappings "
        "with low confidence, suggest better column mappings. Return only JSON with "
        '{"fields": [{"entity", "field", "column", "confidence"}]}. '
        "Only suggest columns that exist in the entity's mapped table."
    )
    user = json.dumps(prompt, indent=2)

    try:
        response = llm.complete(system, user)
        suggestions = json.loads(response)
        for sugg in suggestions.get("fields", []):
            entity = sugg.get("entity")
            field = sugg.get("field")
            column = sugg.get("column")
            confidence = sugg.get("confidence", 0.5)
            if entity not in mapping.entities:
                continue
            table = mapping.entities[entity]
            table_profile = profile.tables.get(table)
            if not table_profile:
                continue
            valid_columns = {c.name for c in table_profile.columns}
            if column not in valid_columns:
                continue
            # Update existing field map
            for fm in mapping.fields:
                if fm.entity == entity and fm.field == field:
                    fm.column = column
                    fm.confidence = confidence
                    fm.source = "llm"
                    break
    except Exception:
        logger.exception("LLM refine failed")

    return mapping


def map_schema(profile: SchemaProfile, llm: LLM | None = None) -> Mapping:
    """Create full schema mapping, optionally refined by LLM."""
    mapping = heuristic_map(profile)
    if llm is not None:
        mapping = llm_refine(mapping, profile, llm)
    return mapping
