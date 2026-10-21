"""Rule learning and conflict detection for RevenueLens."""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.mapping import Mapping


@dataclass
class Rule:
    """Learned rule from configuration or billing data."""

    rule_id: str
    kind: str
    key: str
    value: float | str
    source: str
    confidence: float
    status: str = "proposed"


@dataclass
class Catalog:
    """Collection of learned rules."""

    rules: list[Rule]

    def get(self, kind: str, key: str) -> Rule | None:
        """Get a rule by kind and key."""
        for rule in self.rules:
            if rule.kind == kind and rule.key == key:
                return rule
        return None

    def by_kind(self, kind: str) -> list[Rule]:
        """Get all rules of a specific kind."""
        return [r for r in self.rules if r.kind == kind]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {"rules": [dataclasses.asdict(r) for r in self.rules]}


def learn_catalog(adapter: ReadOnlyAdapter, mapping: Mapping) -> Catalog:
    """Learn rules from configuration tables and billed data."""
    rules: list[Rule] = []
    rule_counter = 0

    def next_rule_id() -> str:
        nonlocal rule_counter
        rule_counter += 1
        return f"R{rule_counter:04d}"

    def quantize_decimal(val: Decimal) -> float:
        return float(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    # Helper to get column name for entity.field
    def col(entity: str, field: str) -> str | None:
        return mapping.column(entity, field)

    # Helper to get table name for entity
    def tbl(entity: str) -> str | None:
        return mapping.table(entity)

    # Plan configuration rules
    plan_table = tbl("plan")
    if plan_table:
        plan_id_col = col("plan", "plan_id")
        monthly_fee_col = col("plan", "monthly_fee")
        incl_data_col = col("plan", "included_data")
        ovg_rate_col = col("plan", "overage_rate")
        if all([plan_id_col, monthly_fee_col, incl_data_col, ovg_rate_col]):
            rows = adapter.fetch_all(plan_table, [plan_id_col, monthly_fee_col, incl_data_col, ovg_rate_col])
            for row in rows:
                pid = str(row[plan_id_col])
                source = f"config:{plan_table}[{plan_id_col}={pid}]"
                rules.append(Rule(next_rule_id(), "plan_fee", pid, quantize_decimal(Decimal(str(row[monthly_fee_col]))), source, 1.0))
                rules.append(Rule(next_rule_id(), "included_data", pid, quantize_decimal(Decimal(str(row[incl_data_col]))), source, 1.0))
                rules.append(Rule(next_rule_id(), "overage_rate", pid, quantize_decimal(Decimal(str(row[ovg_rate_col]))), source, 1.0))

    # Rate configuration rules
    rate_table = tbl("rate")
    if rate_table:
        rate_id_col = col("rate", "rate_id")
        plan_id_col = col("rate", "plan_id")
        usage_type_col = col("rate", "usage_type")
        unit_rate_col = col("rate", "unit_rate")
        if all([rate_id_col, plan_id_col, usage_type_col, unit_rate_col]):
            rows = adapter.fetch_all(rate_table, [rate_id_col, plan_id_col, usage_type_col, unit_rate_col])
            for row in rows:
                pid = str(row[plan_id_col])
                utype = str(row[usage_type_col])
                key = f"{pid}:{utype}"
                source = f"config:{rate_table}[{rate_id_col}={row[rate_id_col]}]"
                rules.append(Rule(next_rule_id(), "usage_rate", key, quantize_decimal(Decimal(str(row[unit_rate_col]))), source, 1.0))

    # Discount configuration rules
    disc_table = tbl("discount")
    if disc_table:
        disc_id_col = col("discount", "discount_id")
        pct_col = col("discount", "percent")
        valid_from_col = col("discount", "valid_from")
        valid_to_col = col("discount", "valid_to")
        if all([disc_id_col, pct_col, valid_from_col, valid_to_col]):
            rows = adapter.fetch_all(disc_table, [disc_id_col, pct_col, valid_from_col, valid_to_col])
            for row in rows:
                did = str(row[disc_id_col])
                source = f"config:{disc_table}[{disc_id_col}={did}]"
                rules.append(Rule(next_rule_id(), "discount_pct", did, quantize_decimal(Decimal(str(row[pct_col]))), source, 1.0))
                vfrom = str(row[valid_from_col])
                vto = str(row[valid_to_col])
                window = f"{vfrom}..{vto}"
                rules.append(Rule(next_rule_id(), "discount_window", did, window, source, 1.0))

    # Observed fee rules from invoice lines (RECUR)
    inv_line_table = tbl("invoice_line")
    if inv_line_table:
        charge_type_col = col("invoice_line", "charge_type")
        charge_ref_col = col("invoice_line", "charge_ref")
        amount_col = col("invoice_line", "amount")
        if all([charge_type_col, charge_ref_col, amount_col]):
            rows = adapter.fetch_all(inv_line_table, [charge_type_col, charge_ref_col, amount_col])
            recurr_rows = [r for r in rows if str(r[charge_type_col]).upper() == "RECUR"]
            by_ref: dict[str, list[Decimal]] = {}
            for row in recurr_rows:
                ref = str(row[charge_ref_col])
                amt = Decimal(str(row[amount_col]))
                by_ref.setdefault(ref, []).append(amt)

            for ref, amounts in by_ref.items():
                if not amounts:
                    continue
                counter = Counter(amounts)
                mode_amt, mode_count = counter.most_common(1)[0]
                share = mode_count / len(amounts)
                source = f"billed:{inv_line_table} n={len(amounts)}"
                rules.append(Rule(next_rule_id(), "observed_fee", ref, quantize_decimal(mode_amt), source, share))

    return Catalog(rules=rules)


def conflicts(catalog: Catalog) -> list[dict]:
    """Detect conflicts between config and observed fees."""
    result = []
    plan_fees = {r.key: r for r in catalog.by_kind("plan_fee")}
    observed_fees = {r.key: r for r in catalog.by_kind("observed_fee")}

    for key, pf in plan_fees.items():
        if key in observed_fees:
            of = observed_fees[key]
            if abs(pf.value - of.value) > 0.001:  # Different values
                result.append(
                    {
                        "plan": key,
                        "config": pf.value,
                        "observed": of.value,
                        "source_config": pf.source,
                        "source_observed": of.source,
                    }
                )
    return result
