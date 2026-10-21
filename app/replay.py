"""Bill replay and validation for RevenueLens."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.learning import Catalog
    from app.mapping import Mapping


@dataclass
class InvoiceReplay:
    """Result of replaying a single invoice."""

    invoice_id: str
    period: str
    expected: float
    actual: float
    diff: float
    matched: bool


@dataclass
class ReplayResult:
    """Result of replaying multiple invoices."""

    invoices: list[InvoiceReplay]
    match_rate: float
    matched: int
    total: int

    def mismatches(self) -> list[InvoiceReplay]:
        """Return only mismatched invoices."""
        return [inv for inv in self.invoices if not inv.matched]

    def to_dict(self) -> dict:
        """Convert to dictionary with summary and first 50 mismatches."""
        mismatches = self.mismatches()
        return {
            "match_rate": self.match_rate,
            "matched": self.matched,
            "total": self.total,
            "mismatches": [
                dataclasses.asdict(m) for m in mismatches[:50]
            ],
        }


def replay_bills(
    adapter: ReadOnlyAdapter,
    mapping: Mapping,
    catalog: Catalog | None = None,
    period: str | None = None,
    tolerance: float = 0.01,
) -> ReplayResult:
    """Replay bills and compare with actual invoices."""
    # Get column names from mapping
    def col(entity: str, field: str) -> str | None:
        return mapping.column(entity, field)

    def tbl(entity: str) -> str | None:
        return mapping.table(entity)

    # Load required tables
    inv_hdr_table = tbl("invoice")
    inv_line_table = tbl("invoice_line")
    contract_table = tbl("contract")
    discount_table = tbl("discount")
    rated_evt_table = tbl("rated_event")
    subscr_table = tbl("subscription")

    if not all([inv_hdr_table, inv_line_table, contract_table, rated_evt_table, subscr_table]):
        return ReplayResult(invoices=[], match_rate=0.0, matched=0, total=0)

    # Column names
    inv_id_col = col("invoice", "invoice_id")
    inv_acct_col = col("invoice", "billing_account")
    inv_cust_col = col("invoice", "customer_id")
    inv_prd_col = col("invoice", "period")
    inv_tot_col = col("invoice", "total")

    line_inv_col = col("invoice_line", "invoice_id")
    line_subscr_col = col("invoice_line", "subscription_id")
    line_type_col = col("invoice_line", "charge_type")
    line_ref_col = col("invoice_line", "charge_ref")
    line_amt_col = col("invoice_line", "amount")

    cntr_id_col = col("contract", "contract_id")
    cntr_cust_col = col("contract", "customer_id")
    cntr_fee_col = col("contract", "agreed_fee")
    cntr_disc_col = col("contract", "discount_id")
    cntr_start_col = col("contract", "start")
    cntr_end_col = col("contract", "end")

    disc_id_col = col("discount", "discount_id")
    disc_pct_col = col("discount", "percent")
    disc_from_col = col("discount", "valid_from")
    disc_to_col = col("discount", "valid_to")

    rtd_subscr_col = col("rated_event", "subscription_id")
    rtd_prd_col = col("rated_event", "period")
    rtd_amt_col = col("rated_event", "amount")

    subscr_id_col = col("subscription", "subscription_id")
    subscr_cust_col = col("subscription", "customer_id")

    if not all([
        inv_id_col, inv_acct_col, inv_cust_col, inv_prd_col, inv_tot_col,
        line_inv_col, line_subscr_col, line_type_col, line_ref_col, line_amt_col,
        cntr_id_col, cntr_cust_col, cntr_fee_col, cntr_disc_col,
        disc_id_col, disc_pct_col, disc_from_col, disc_to_col,
        rtd_subscr_col, rtd_prd_col, rtd_amt_col,
        subscr_id_col, subscr_cust_col,
    ]):
        return ReplayResult(invoices=[], match_rate=0.0, matched=0, total=0)

    # Fetch all data
    invoices = adapter.fetch_all(inv_hdr_table)
    if period:
        invoices = [inv for inv in invoices if str(inv[inv_prd_col]) == period]

    invoice_lines = adapter.fetch_all(inv_line_table)
    contracts = adapter.fetch_all(contract_table)
    discounts = adapter.fetch_all(discount_table)
    rated_events = adapter.fetch_all(rated_evt_table)
    subscriptions = adapter.fetch_all(subscr_table)

    # Index rated events by (subscription_id, period) -> sum amount
    rated_index: dict[tuple[str, str], Decimal] = {}
    for re in rated_events:
        sub_id = str(re[rtd_subscr_col])
        prd = str(re[rtd_prd_col])
        amt = Decimal(str(re[rtd_amt_col]))
        key = (sub_id, prd)
        rated_index[key] = rated_index.get(key, Decimal(0)) + amt

    # Index subscriptions by customer_id -> list of subscription_ids
    subscr_by_cust: dict[str, list[str]] = {}
    for sub in subscriptions:
        cust = str(sub[subscr_cust_col])
        sub_id = str(sub[subscr_id_col])
        subscr_by_cust.setdefault(cust, []).append(sub_id)

    # Index contracts by customer_id
    contracts_by_cust: dict[str, list[dict]] = {}
    for cntr in contracts:
        cust = str(cntr[cntr_cust_col])
        contracts_by_cust.setdefault(cust, []).append(cntr)

    # Index discounts by discount_id
    discounts_by_id: dict[str, dict] = {}
    for disc in discounts:
        did = str(disc[disc_id_col])
        discounts_by_id[did] = disc

    # Group invoice lines by invoice_id
    lines_by_inv: dict[str, list[dict]] = {}
    for line in invoice_lines:
        inv_id = str(line[line_inv_col])
        lines_by_inv.setdefault(inv_id, []).append(line)

    results: list[InvoiceReplay] = []
    matched_count = 0

    for inv in invoices:
        inv_id = str(inv[inv_id_col])
        inv_prd = str(inv[inv_prd_col])
        inv_cust = str(inv[inv_cust_col])
        actual = Decimal(str(inv[inv_tot_col]))

        # Determine RECUR subscription ids for this invoice
        inv_lines = lines_by_inv.get(inv_id, [])
        sub_ids = sorted(
            {
                str(line[line_subscr_col])
                for line in inv_lines
                if str(line[line_type_col]) == "RECUR"
            }
        )

        if not sub_ids:
            expected = Decimal(0)
        else:
            # Find contract for this customer
            cust_contracts = contracts_by_cust.get(inv_cust, [])
            contract = None
            for cntr in cust_contracts:
                start = cntr[cntr_start_col]
                end = cntr[cntr_end_col]
                if start and end:
                    contract = cntr
                    break
            if not contract and cust_contracts:
                contract = cust_contracts[0]

            if not contract:
                expected = Decimal(0)
            else:
                agreed_fee = Decimal(str(contract[cntr_fee_col]))
                disc_id = contract[cntr_disc_col]

                expected = Decimal(0)

                # Process each subscription present on this invoice
                for sub_id in sub_ids:
                    # RECUR line fee
                    expected += agreed_fee
                    # USAGE lines from rated events
                    expected += rated_index.get((sub_id, inv_prd), Decimal(0))
                    # DISC line per subscription if applicable
                    if disc_id and (disc := discounts_by_id.get(str(disc_id))):
                        disc_from = disc[disc_from_col]
                        disc_to = disc[disc_to_col]
                        pct = Decimal(str(disc[disc_pct_col]))
                        try:
                            prd_year = int(inv_prd[:4])
                            prd_month = int(inv_prd[4:6])
                            period_first_day = date(prd_year, prd_month, 1)
                            if isinstance(disc_from, str):
                                disc_from_date = date.fromisoformat(disc_from)
                            else:
                                disc_from_date = disc_from
                            if isinstance(disc_to, str):
                                disc_to_date = date.fromisoformat(disc_to)
                            else:
                                disc_to_date = disc_to
                            if disc_from_date and disc_to_date and disc_from_date <= period_first_day <= disc_to_date:
                                disc_amt = (agreed_fee * pct).quantize(
                                    Decimal("0.01"), rounding=ROUND_HALF_UP
                                )
                                expected -= disc_amt
                        except (ValueError, IndexError, TypeError):
                            pass

        diff = float(expected - actual)
        matched = abs(diff) <= tolerance
        if matched:
            matched_count += 1

        results.append(
            InvoiceReplay(
                invoice_id=inv_id,
                period=inv_prd,
                expected=float(expected),
                actual=float(actual),
                diff=diff,
                matched=matched,
            )
        )

    total = len(results)
    match_rate = matched_count / total if total > 0 else 0.0

    return ReplayResult(
        invoices=results,
        match_rate=match_rate,
        matched=matched_count,
        total=total,
    )
