"""Revenue reconciliation checks for RevenueLens step 4."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.adapters.postgres_readonly import ReadOnlyAdapter
from app.discovery import discover

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Finding:
    """Represents a single revenue leak finding."""

    check: str
    record_ids: list[str]
    table: str
    customer_id: str | None
    period: str | None
    impact: float
    evidence: dict
    description: str


class Data:
    """Container for all mapped entities, re-keyed to canonical field names."""

    def __init__(self) -> None:
        self._entities: dict[str, list[dict[str, Any]]] = {}
        self._table_names: dict[str, str] = {}

    @classmethod
    def load(cls, adapter: ReadOnlyAdapter, mapping: Any) -> Data:
        """Load all mapped entities from the database."""
        instance = cls()
        discover(adapter)

        # Get all canonical entities from the mapping
        entities = [
            "plan",
            "rate",
            "discount",
            "contract",
            "subscription",
            "usage",
            "rated_event",
            "invoice",
            "invoice_line",
            "payment",
            "renewal",
        ]

        for entity in entities:
            table_name = mapping.table(entity)
            if table_name is None:
                instance._entities[entity] = []
                continue

            instance._table_names[entity] = table_name
            rows = adapter.fetch_all(table_name)
            canonical_rows = []
            for row in rows:
                canon_row: dict[str, Any] = {}
                # Map each canonical field
                fields = [
                    "plan_id",
                    "description",
                    "monthly_fee",
                    "rate_id",
                    "usage_type",
                    "unit_rate",
                    "valid_from",
                    "valid_to",
                    "discount_id",
                    "percent",
                    "contract_id",
                    "customer_id",
                    "agreed_fee",
                    "discount_id",
                    "start",
                    "end",
                    "auto_renew",
                    "subscription_id",
                    "msisdn",
                    "activated",
                    "deactivated",
                    "status",
                    "billing_account",
                    "usage_id",
                    "timestamp",
                    "quantity",
                    "rated_flag",
                    "rated_id",
                    "period",
                    "amount",
                    "invoiced_flag",
                    "invoice_id",
                    "billing_account",
                    "invoice_date",
                    "total",
                    "due_date",
                    "line_no",
                    "charge_type",
                    "charge_ref",
                    "payment_id",
                    "payment_date",
                    "channel",
                    "renewal_id",
                    "due_date",
                    "new_end",
                ]
                for field in fields:
                    col = mapping.column(entity, field)
                    if col and col in row:
                        value = row[col]
                        if isinstance(value, (int, float, Decimal)):
                            canon_row[field] = value
                        else:
                            canon_row[field] = str(value) if value is not None else None
                canonical_rows.append(canon_row)
            instance._entities[entity] = canonical_rows

        return instance

    def __getitem__(self, key: str) -> list[dict[str, Any]]:
        return self._entities.get(key, [])

    def __contains__(self, key: str) -> bool:
        return key in self._entities

    def get(self, key: str, default: Any = None) -> Any:
        if key == "_tables":
            return self._table_names
        return self._entities.get(key, default)

    @property
    def _tables(self) -> dict[str, str]:
        return self._table_names


def _to_decimal(value: Any) -> Decimal:
    """Convert value to Decimal, handling None."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round2(value: Decimal) -> float:
    """Round Decimal to 2 decimal places and return as float."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def check_unrated_usage(d: dict[str, list[dict]]) -> list[Finding]:
    """Find usage records that were never rated."""
    findings = []
    usage_rows = d.get("usage", [])
    rated_rows = d.get("rated_event", [])
    subscription_rows = d.get("subscription", [])
    plan_rows = d.get("plan", [])
    rate_rows = d.get("rate", [])

    # Build lookup maps
    rated_usage_ids = {str(r.get("usage_id")) for r in rated_rows if r.get("usage_id")}
    sub_by_id = {str(r.get("subscription_id")): r for r in subscription_rows if r.get("subscription_id")}
    plan_by_id = {str(r.get("plan_id")): r for r in plan_rows if r.get("plan_id")}

    # Build rate lookup: (plan_id, usage_type) -> unit_rate
    rate_lookup: dict[tuple[str, str], Decimal] = {}
    for rate in rate_rows:
        plan_id = str(rate.get("plan_id", ""))
        usage_type = str(rate.get("usage_type", ""))
        unit_rate = _to_decimal(rate.get("unit_rate"))
        if plan_id and usage_type:
            rate_lookup[(plan_id, usage_type)] = unit_rate

    usage_table = d.get("_tables", {}).get("usage", "usage")

    for usage in usage_rows:
        usage_id = str(usage.get("usage_id", ""))
        rated_flag = str(usage.get("rated_flag", "")).upper()

        # Check if unrated
        if rated_flag == "N" or usage_id not in rated_usage_ids:
            subscription_id = str(usage.get("subscription_id", ""))
            usage_type = str(usage.get("usage_type", ""))
            quantity = _to_decimal(usage.get("quantity"))

            # Find unit rate via subscription -> plan -> rate
            sub = sub_by_id.get(subscription_id)
            plan_id = str(sub.get("plan_id", "")) if sub else ""
            plan_by_id.get(plan_id) if plan_id else None

            unit_rate = rate_lookup.get((plan_id, usage_type), Decimal(0))

            impact = _round2(quantity * unit_rate)

            findings.append(
                Finding(
                    check="unrated_usage",
                    record_ids=[usage_id],
                    table=usage_table,
                    customer_id=None,
                    period=None,
                    impact=impact,
                    evidence={
                        "usage_id": usage_id,
                        "subscription_id": subscription_id,
                        "usage_type": usage_type,
                        "quantity": str(quantity),
                        "unit_rate": str(unit_rate),
                        "rated_flag": rated_flag,
                    },
                    description=f"Usage {usage_id} not rated (flag={rated_flag}, no rated_event)",
                )
            )

    return findings


def check_rated_not_invoiced(d: dict[str, list[dict]]) -> list[Finding]:
    """Find rated events that were never invoiced."""
    findings = []
    rated_rows = d.get("rated_event", [])
    invoice_line_rows = d.get("invoice_line", [])

    # Build set of rated_ids referenced in invoice lines
    invoiced_rated_ids = set()
    for line in invoice_line_rows:
        charge_ref = str(line.get("charge_ref", ""))
        if charge_ref.startswith("RTD:"):
            rated_id = charge_ref[4:]
            invoiced_rated_ids.add(rated_id)

    rated_table = d.get("_tables", {}).get("rated_event", "rated_event")

    for rated in rated_rows:
        rated_id = str(rated.get("rated_id", ""))
        invoiced_flag = str(rated.get("invoiced_flag", "")).upper()
        amount = _to_decimal(rated.get("amount"))

        if invoiced_flag == "N" or rated_id not in invoiced_rated_ids:
            findings.append(
                Finding(
                    check="rated_not_invoiced",
                    record_ids=[rated_id],
                    table=rated_table,
                    customer_id=str(rated.get("customer_id")) if rated.get("customer_id") else None,
                    period=str(rated.get("period")) if rated.get("period") else None,
                    impact=_round2(amount),
                    evidence={
                        "rated_id": rated_id,
                        "subscription_id": str(rated.get("subscription_id", "")),
                        "period": str(rated.get("period", "")),
                        "amount": str(amount),
                        "invoiced_flag": invoiced_flag,
                    },
                    description=f"Rated event {rated_id} not invoiced (flag={invoiced_flag}, no invoice line)",
                )
            )

    return findings


def check_tariff_mismatch(d: dict[str, list[dict]]) -> list[Finding]:
    """Find RECUR invoice lines where amount != contract agreed_fee."""
    findings = []
    invoice_line_rows = d.get("invoice_line", [])
    invoice_rows = d.get("invoice", [])
    contract_rows = d.get("contract", [])

    # Build lookups
    invoice_by_id = {str(r.get("invoice_id")): r for r in invoice_rows if r.get("invoice_id")}
    contract_by_customer: dict[str, list[dict]] = {}
    for contract in contract_rows:
        cust_id = str(contract.get("customer_id", ""))
        if cust_id:
            contract_by_customer.setdefault(cust_id, []).append(contract)

    # Get duplicate charge record ids to skip
    for line in invoice_line_rows:
        charge_type = str(line.get("charge_type", ""))
        if charge_type == "RECUR":
            # We'll check duplicates later, but for now we need to know which are flagged
            pass

    # Actually, we need to run duplicate check logic here to know which to skip
    # But checks are independent. The spec says "Skip lines that are flagged as duplicates by check 8 (the duplicate copy)"
    # This means we need to identify duplicates first. Since checks are independent functions,
    # we'll compute duplicates inline here.
    seen: dict[tuple[str, str, str, Decimal], list[dict]] = {}
    for line in invoice_line_rows:
        charge_type = str(line.get("charge_type", ""))
        if charge_type != "RECUR":
            continue
        invoice_id = str(line.get("invoice_id", ""))
        sub_id = str(line.get("subscription_id", ""))
        charge_ref = str(line.get("charge_ref", ""))
        amount = _to_decimal(line.get("amount"))
        line_no = str(line.get("line_no", ""))
        key = (invoice_id, sub_id, charge_ref, amount)
        seen.setdefault(key, []).append({"line_no": line_no, "line": line})

    duplicate_line_ids = set()
    for key, lines in seen.items():
        if len(lines) > 1:
            # Sort by line_no, skip first
            lines.sort(key=lambda x: int(x["line_no"]) if x["line_no"].isdigit() else 0)
            for dup in lines[1:]:
                invoice_id = key[0]
                line_no = dup["line_no"]
                duplicate_line_ids.add(f"{invoice_id}:{line_no}")

    invoice_table = d.get("_tables", {}).get("invoice", "invoice")

    for line in invoice_line_rows:
        charge_type = str(line.get("charge_type", ""))
        if charge_type != "RECUR":
            continue

        invoice_id = str(line.get("invoice_id", ""))
        line_no = str(line.get("line_no", ""))
        line_key = f"{invoice_id}:{line_no}"

        if line_key in duplicate_line_ids:
            continue

        amount = _to_decimal(line.get("amount"))
        sub_id = str(line.get("subscription_id", ""))

        # Find invoice to get customer_id
        invoice = invoice_by_id.get(invoice_id)
        if not invoice:
            continue
        customer_id = str(invoice.get("customer_id", ""))

        # Find contract for this customer
        contracts = contract_by_customer.get(customer_id, [])
        if not contracts:
            continue

        # Use the first contract (assuming one active contract per customer)
        contract = contracts[0]
        agreed_fee = _to_decimal(contract.get("agreed_fee"))

        diff = amount - agreed_fee
        if diff != 0:
            findings.append(
                Finding(
                    check="tariff_mismatch",
                    record_ids=[line_key],
                    table=invoice_table,
                    customer_id=customer_id,
                    period=str(invoice.get("period")) if invoice.get("period") else None,
                    impact=_round2(diff),
                    evidence={
                        "invoice_id": invoice_id,
                        "line_no": line_no,
                        "subscription_id": sub_id,
                        "invoiced_amount": str(amount),
                        "agreed_fee": str(agreed_fee),
                        "difference": str(diff),
                    },
                    description=f"Invoice line {line_key} amount {amount} != contract agreed_fee {agreed_fee}",
                )
            )

    return findings


def check_expired_discount(d: dict[str, list[dict]]) -> list[Finding]:
    """Find DISC invoice lines where discount window doesn't contain invoice period start."""
    findings = []
    invoice_line_rows = d.get("invoice_line", [])
    invoice_rows = d.get("invoice", [])
    discount_rows = d.get("discount", [])

    discount_by_id = {str(r.get("discount_id")): r for r in discount_rows if r.get("discount_id")}
    invoice_by_id = {str(r.get("invoice_id")): r for r in invoice_rows if r.get("invoice_id")}

    invoice_table = d.get("_tables", {}).get("invoice", "invoice")

    for line in invoice_line_rows:
        charge_type = str(line.get("charge_type", ""))
        if charge_type != "DISC":
            continue

        invoice_id = str(line.get("invoice_id", ""))
        line_no = str(line.get("line_no", ""))
        line_key = f"{invoice_id}:{line_no}"
        charge_ref = str(line.get("charge_ref", ""))  # This is discount_id
        amount = _to_decimal(line.get("amount"))

        discount = discount_by_id.get(charge_ref)
        if not discount:
            continue

        invoice = invoice_by_id.get(invoice_id)
        if not invoice:
            continue

        period = str(invoice.get("period", ""))
        if not period or len(period) != 6:
            continue

        # First day of invoice period
        try:
            year = int(period[:4])
            month = int(period[4:6])
            period_start = f"{year:04d}-{month:02d}-01"
        except ValueError:
            continue

        valid_from = str(discount.get("valid_from", ""))
        valid_to = str(discount.get("valid_to", ""))

        # Check if period_start is within [valid_from, valid_to]
        discount_active = True
        if valid_from and period_start < valid_from:
            discount_active = False
        if valid_to and period_start > valid_to:
            discount_active = False

        if not discount_active:
            findings.append(
                Finding(
                    check="expired_discount",
                    record_ids=[line_key],
                    table=invoice_table,
                    customer_id=str(invoice.get("customer_id")) if invoice.get("customer_id") else None,
                    period=period,
                    impact=_round2(-amount),  # Negative = customer overbilled (discount given away)
                    evidence={
                        "invoice_id": invoice_id,
                        "line_no": line_no,
                        "discount_id": charge_ref,
                        "discount_valid_from": valid_from,
                        "discount_valid_to": valid_to,
                        "invoice_period_start": period_start,
                        "discount_amount": str(amount),
                    },
                    description=f"Discount {charge_ref} applied outside validity window on invoice {invoice_id}",
                )
            )

    return findings


def check_provisioned_not_billed(d: dict[str, list[dict]]) -> list[Finding]:
    """Find active subscriptions with no billing account or never on any invoice line."""
    findings = []
    subscription_rows = d.get("subscription", [])
    plan_rows = d.get("plan", [])
    invoice_line_rows = d.get("invoice_line", [])

    plan_by_id = {str(r.get("plan_id")): r for r in plan_rows if r.get("plan_id")}

    # Subscriptions that appear on invoice lines
    billed_sub_ids = set()
    for line in invoice_line_rows:
        sub_id = str(line.get("subscription_id", ""))
        if sub_id:
            billed_sub_ids.add(sub_id)

    subscription_table = d.get("_tables", {}).get("subscription", "subscription")

    for sub in subscription_rows:
        status = str(sub.get("status", "")).upper()
        if status != "ACTIVE":
            continue

        subscription_id = str(sub.get("subscription_id", ""))
        billing_account = sub.get("billing_account")
        plan_id = str(sub.get("plan_id", ""))

        has_billing_account = billing_account is not None and str(billing_account).strip() != ""
        ever_billed = subscription_id in billed_sub_ids

        if not has_billing_account or not ever_billed:
            plan = plan_by_id.get(plan_id)
            monthly_fee = _to_decimal(plan.get("monthly_fee")) if plan else Decimal(0)
            impact = _round2(monthly_fee * 3)  # 3 months of fees

            findings.append(
                Finding(
                    check="provisioned_not_billed",
                    record_ids=[subscription_id],
                    table=subscription_table,
                    customer_id=str(sub.get("customer_id")) if sub.get("customer_id") else None,
                    period=None,
                    impact=impact,
                    evidence={
                        "subscription_id": subscription_id,
                        "customer_id": str(sub.get("customer_id", "")),
                        "plan_id": plan_id,
                        "status": status,
                        "billing_account": str(billing_account) if billing_account else "",
                        "ever_billed": ever_billed,
                        "monthly_fee": str(monthly_fee),
                    },
                    description=(
                        f"Active subscription {subscription_id} not billed "
                        f"(billing_account={'set' if has_billing_account else 'empty'}, "
                        f"ever_billed={ever_billed})"
                    ),
                )
            )

    return findings


def check_missed_renewal(d: dict[str, list[dict]]) -> list[Finding]:
    """Find auto-renew contracts with failed renewal."""
    findings = []
    contract_rows = d.get("contract", [])
    renewal_rows = d.get("renewal", [])
    invoice_rows = d.get("invoice", [])

    # Find latest invoice period across all data
    latest_period = "000000"
    for inv in invoice_rows:
        period = str(inv.get("period", ""))
        if period and period > latest_period:
            latest_period = period

    contract_table = d.get("_tables", {}).get("contract", "contract")

    for contract in contract_rows:
        auto_renew = str(contract.get("auto_renew", "")).upper()
        if auto_renew != "Y":
            continue

        contract_id = str(contract.get("contract_id", ""))
        agreed_fee = _to_decimal(contract.get("agreed_fee"))
        contract_end = str(contract.get("end", ""))

        # Find renewal for this contract
        failed_renewal = False
        for renewal in renewal_rows:
            if (
                str(renewal.get("contract_id", "")) == contract_id
                and str(renewal.get("status", "")).upper() == "FAILED"
            ):
                failed_renewal = True
                break

        if not failed_renewal:
            continue

        # Calculate months between contract end and latest invoice period
        try:
            end_year = int(contract_end[:4])
            end_month = int(contract_end[4:6])
            latest_year = int(latest_period[:4])
            latest_month = int(latest_period[4:6])
            months_diff = (latest_year - end_year) * 12 + (latest_month - end_month)
            months_diff = max(1, months_diff)
        except (ValueError, IndexError):
            months_diff = 1

        impact = _round2(agreed_fee * months_diff)

        findings.append(
            Finding(
                check="missed_renewal",
                record_ids=[contract_id],
                table=contract_table,
                customer_id=str(contract.get("customer_id")) if contract.get("customer_id") else None,
                period=latest_period if latest_period != "000000" else None,
                impact=impact,
                evidence={
                    "contract_id": contract_id,
                    "customer_id": str(contract.get("customer_id", "")),
                    "agreed_fee": str(agreed_fee),
                    "contract_end": contract_end,
                    "latest_invoice_period": latest_period,
                    "months_lost": months_diff,
                },
                description=f"Contract {contract_id} auto-renew failed, lost {months_diff} months of revenue",
            )
        )

    return findings


def check_unmatched_payment(d: dict[str, list[dict]]) -> list[Finding]:
    """Find payments with no matching invoice."""
    findings = []
    payment_rows = d.get("payment", [])
    invoice_rows = d.get("invoice", [])

    invoice_ids = {str(r.get("invoice_id")) for r in invoice_rows if r.get("invoice_id")}

    payment_table = d.get("_tables", {}).get("payment", "payment")

    for payment in payment_rows:
        payment_id = str(payment.get("payment_id", ""))
        invoice_id = str(payment.get("invoice_id", "")) if payment.get("invoice_id") else ""
        amount = _to_decimal(payment.get("amount"))

        if not invoice_id or invoice_id not in invoice_ids:
            findings.append(
                Finding(
                    check="unmatched_payment",
                    record_ids=[payment_id],
                    table=payment_table,
                    customer_id=str(payment.get("customer_id")) if payment.get("customer_id") else None,
                    period=None,
                    impact=_round2(amount),
                    evidence={
                        "payment_id": payment_id,
                        "customer_id": str(payment.get("customer_id", "")),
                        "invoice_id": invoice_id,
                        "amount": str(amount),
                        "payment_date": str(payment.get("payment_date", "")),
                    },
                    description=f"Payment {payment_id} has no matching invoice (invoice_id={invoice_id or 'empty'})",
                )
            )

    return findings


def check_duplicate_charge(d: dict[str, list[dict]]) -> list[Finding]:
    """Find duplicate RECUR lines within an invoice."""
    findings = []
    invoice_line_rows = d.get("invoice_line", [])
    invoice_rows = d.get("invoice", [])

    invoice_by_id = {str(r.get("invoice_id")): r for r in invoice_rows if r.get("invoice_id")}

    # Group by (invoice_id, subscription_id, charge_ref, amount)
    groups: dict[tuple[str, str, str, Decimal], list[dict]] = {}
    for line in invoice_line_rows:
        charge_type = str(line.get("charge_type", ""))
        if charge_type != "RECUR":
            continue
        invoice_id = str(line.get("invoice_id", ""))
        sub_id = str(line.get("subscription_id", ""))
        charge_ref = str(line.get("charge_ref", ""))
        amount = _to_decimal(line.get("amount"))
        line_no = str(line.get("line_no", ""))
        key = (invoice_id, sub_id, charge_ref, amount)
        groups.setdefault(key, []).append({"line_no": line_no, "line": line})

    invoice_table = d.get("_tables", {}).get("invoice", "invoice")

    for key, lines in groups.items():
        if len(lines) <= 1:
            continue
        # Sort by line_no ascending
        lines.sort(key=lambda x: int(x["line_no"]) if x["line_no"].isdigit() else 0)
        # First is original, rest are duplicates
        for dup in lines[1:]:
            line = dup["line"]
            invoice_id = key[0]
            line_no = dup["line_no"]
            line_key = f"{invoice_id}:{line_no}"
            amount = _to_decimal(line.get("amount"))
            invoice = invoice_by_id.get(invoice_id)

            findings.append(
                Finding(
                    check="duplicate_charge",
                    record_ids=[line_key],
                    table=invoice_table,
                    customer_id=str(invoice.get("customer_id")) if invoice and invoice.get("customer_id") else None,
                    period=str(invoice.get("period")) if invoice and invoice.get("period") else None,
                    impact=_round2(-amount),  # Negative = customer overbilled
                    evidence={
                        "invoice_id": invoice_id,
                        "line_no": line_no,
                        "subscription_id": key[1],
                        "charge_ref": key[2],
                        "amount": str(amount),
                        "original_line_no": lines[0]["line_no"],
                    },
                    description=f"Duplicate charge on invoice {invoice_id} line {line_no} (original line {lines[0]['line_no']})",
                )
            )

    return findings


CHECKS: dict[str, Any] = {
    "unrated_usage": check_unrated_usage,
    "rated_not_invoiced": check_rated_not_invoiced,
    "tariff_mismatch": check_tariff_mismatch,
    "expired_discount": check_expired_discount,
    "provisioned_not_billed": check_provisioned_not_billed,
    "missed_renewal": check_missed_renewal,
    "unmatched_payment": check_unmatched_payment,
    "duplicate_charge": check_duplicate_charge,
}


def run_checks(adapter: ReadOnlyAdapter, mapping: Any) -> list[Finding]:
    """Run all reconciliation checks."""
    data = Data.load(adapter, mapping)
    all_findings: list[Finding] = []
    for name, check_fn in CHECKS.items():
        logger.info("Running check: %s", name)
        findings = check_fn(data)
        all_findings.extend(findings)
        logger.info("Check %s found %d findings", name, len(findings))
    return all_findings


def summarize(findings: list[Finding]) -> dict[str, Any]:
    """Summarize findings by check and overall."""
    summary: dict[str, dict[str, Any]] = {}
    total_impact = Decimal(0)

    for finding in findings:
        check_name = finding.check
        if check_name not in summary:
            summary[check_name] = {"count": 0, "impact": Decimal(0)}
        summary[check_name]["count"] += 1
        summary[check_name]["impact"] += Decimal(str(finding.impact))
        total_impact += Decimal(str(finding.impact))

    result: dict[str, Any] = {}
    for check_name, stats in summary.items():
        result[check_name] = {"count": stats["count"], "impact": float(stats["impact"])}
    result["total_impact"] = float(total_impact)
    return result
