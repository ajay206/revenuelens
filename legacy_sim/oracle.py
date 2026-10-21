"""Leak detection oracle for the Nimbus Telecom legacy billing simulation.

The functions operate directly on the generated `Dataset` structure without
reading the ground‑truth data.  They return a mapping from leak type to a set of
identifiers that match the format used in the ground‑truth records.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from .generator import Dataset


def _first_day_of_month(bill_prd: str) -> date:
    """Convert a billing period like '202607' to the first day of that month."""
    year = int(bill_prd[:4])
    month = int(bill_prd[4:6])
    return date(year, month, 1)


def find_leaks(ds: Dataset) -> dict[str, set[str]]:
    """Detect the eight leak types (excluding config_conflict) in the dataset.

    The return value maps the leak type name (as used in the ground‑truth) to a
    set of string identifiers.  The identifier format matches the `record_ids`
    field in the ground‑truth examples.

    Parameters
    ----------
    ds:
        The generated dataset.

    Returns
    -------
    dict[str, set[str]]
        Mapping from leak type to a set of record identifiers.
    """
    tables = ds.tables
    leaks: dict[str, set[str]] = defaultdict(set)

    # ---------- Helper look‑ups ----------
    # Build index structures that will be reused across the checks.
    {row["CDR_ID"]: row for row in tables.get("USG_CDR", [])}
    {row["RTD_ID"]: row for row in tables.get("RTD_EVT", [])}
    bill_hdr_by_inv = {row["INV_NO"]: row for row in tables.get("BILL_HDR", [])}
    bill_dtl_by_ref: dict[str, set[int]] = defaultdict(set)
    for row in tables.get("BILL_DTL", []):
        ref = row.get("CHG_REF")
        if ref and ref.startswith("RTD:"):
            try:
                rtd_id = int(ref.split(":", 1)[1])
                bill_dtl_by_ref.setdefault(rtd_id, set()).add(row["LN_NO"])
            except ValueError:
                pass

    # Map subscription to its contract (via CUST_NO)
    # First, cust_no per subscription
    {
        row["SUBSCR_ID"]: row["CUST_NO"] for row in tables.get("SUBSCR_MSTR", [])
    }
    # Contract terms per cust_no (take the active one)
    contract_by_cust: dict[str, dict] = {}
    for row in tables.get("CONTRACT_TERMS", []):
        contract_by_cust[row["CUST_NO"]] = row

    # Discount config by DISC_CD
    disc_cfg_by_cd: dict[str, dict] = {
        row["DISC_CD"]: row for row in tables.get("DISC_CFG", [])
    }

    # ---------- 1. unrated_usage ----------
    for row in tables.get("USG_CDR", []):
        if row["RATED_FLG"] == "N":
            leaks["unrated_usage"].add(str(row["CDR_ID"]))
            continue
        # If there is a rated flag but no corresponding RTD_EVT
        cdr_id = row["CDR_ID"]
        if not any(rtd["CDR_ID"] == cdr_id for rtd in tables.get("RTD_EVT", [])):
            leaks["unrated_usage"].add(str(cdr_id))

    # ---------- 2. rated_not_invoiced ----------
    for rtd in tables.get("RTD_EVT", []):
        if rtd["INV_FLG"] == "N":
            leaks["rated_not_invoiced"].add(str(rtd["RTD_ID"]))
            continue
        # INV_FLG == 'Y' but not referenced from any BILL_DTL line
        if rtd["RTD_ID"] not in bill_dtl_by_ref:
            leaks["rated_not_invoiced"].add(str(rtd["RTD_ID"]))

    # ---------- 3. tariff_mismatch ----------
    # For each RECUR line, compare its amount to the agreed monthly fee of the
    # subscriber's contract.  The contract fee may be NULL; in that case we do
    # not flag a mismatch.
    for line in tables.get("BILL_DTL", []):
        if line["CHG_TYP"] != "RECUR":
            continue
        inv_no = line["INV_NO"]
        hdr = bill_hdr_by_inv.get(inv_no)
        if not hdr:
            continue
        cust_no = hdr["CUST_NO"]
        contract = contract_by_cust.get(cust_no)
        if not contract:
            continue
        agreed_fee = contract.get("AGREED_MTHLY_FEE")
        if agreed_fee is None:
            continue
        if Decimal(line["AMT"]) != Decimal(agreed_fee):
            # Build identifier as per ground‑truth: "INV_NO:LN_NO"
            leaks["tariff_mismatch"].add(f"{inv_no}:{line['LN_NO']}")

    # ---------- 4. expired_discount ----------
    # A discount line (CHG_TYP='DISC') is invalid if the invoice period is
    # after the discount's VALID_TO date.
    for line in tables.get("BILL_DTL", []):
        if line["CHG_TYP"] != "DISC":
            continue
        inv_no = line["INV_NO"]
        hdr = bill_hdr_by_inv.get(inv_no)
        if not hdr:
            continue
        disc_cd = line.get("CHG_REF")
        if not disc_cd:
            continue
        disc_cfg = disc_cfg_by_cd.get(disc_cd)
        if not disc_cfg:
            continue
        bill_prd_first = _first_day_of_month(hdr["BILL_PRD"])
        valid_to = disc_cfg["VALID_TO"]
        if valid_to and bill_prd_first > valid_to:
            leaks["expired_discount"].add(f"{inv_no}:{line['LN_NO']}")

    # ---------- 5. provisioned_not_billed ----------
    for sub in tables.get("SUBSCR_MSTR", []):
        if sub["PROV_STAT"] == "ACTIVE" and not sub.get("BILL_ACCT_NO"):
            # Ensure the identifier is a string
            leaks["provisioned_not_billed"].add(str(sub["SUBSCR_ID"]))

    # ---------- 6. missed_renewal ----------
    for log in tables.get("RENEW_LOG", []):
        if log["RNW_STAT"] == "FAILED":
            # Identify the contract to which this log belongs
            cntr_id = log["CNTR_ID"]
            # Find the contract row to get the customer
            contract = next(
                (c for c in tables.get("CONTRACT_TERMS", []) if c["CNTR_ID"] == cntr_id),
                None,
            )
            if contract:
                leaks["missed_renewal"].add(str(contract["CNTR_ID"]))

    # ---------- 7. unmatched_payment ----------
    for pmt in tables.get("PYMT_TXN", []):
        ref = pmt.get("REF_INV_NO")
        if not ref or ref not in bill_hdr_by_inv:
            leaks["unmatched_payment"].add(str(pmt["PYMT_ID"]))

    # ---------- 8. duplicate_charge ----------
    # Within each invoice, find RECUR lines that share the same SUBSCR_ID.
    recur_by_inv: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for line in tables.get("BILL_DTL", []):
        if line["CHG_TYP"] != "RECUR":
            continue
        recur_by_inv[line["INV_NO"]][line["SUBSCR_ID"]].append(line["LN_NO"])

    for inv_no, subs in recur_by_inv.items():
        for ln_nos in subs.values():
            if len(ln_nos) > 1:
                # Keep the first (smallest LN_NO) as the valid line; the rest are duplicates
                for dup_ln in sorted(ln_nos)[1:]:
                    leaks["duplicate_charge"].add(f"{inv_no}:{dup_ln}")

    return dict(leaks)
