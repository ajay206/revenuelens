"""Synthetic legacy billing data generator for Nimbus Telecom.

The module implements a deterministic data generator that produces a
`Dataset` object containing:
* `tables` – a mapping from table name to a list of row dictionaries.
* `ground_truth` – a list of leak descriptions.
* `tickets` – a list of issue‑tracker tickets.
* `pages` – a mapping from markdown filename to its contents.

All random choices are driven by ``random.Random`` with a fixed seed so
that repeated runs are byte‑identical.  Dates are hard‑coded to avoid any
dependency on the current wall‑clock time.

Only the Python standard library is used (no external dependencies).
"""

from __future__ import annotations

import calendar
import datetime as _dt
import json
import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #

_DEC_Q = Decimal("0.01")  # quantisation factor for INR amounts


def _d(val: float | str | Decimal) -> Decimal:
    """Quantise a numeric value to 2‑decimal INR."""
    return Decimal(str(val)).quantize(_DEC_Q, rounding=ROUND_HALF_UP)


def _date(y: int, m: int, d: int) -> _dt.date:
    """Convenient date factory."""
    return _dt.date(y, m, d)


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> _dt.datetime:
    """Convenient timestamp factory."""
    return _dt.datetime(y, m, d, hh, mm, ss)


def _gen_msisdn(rng: random.Random) -> str:
    """Generate a realistic 10‑digit Indian mobile number starting with 98."""
    suffix = "".join(str(rng.randint(0, 9)) for _ in range(8))
    return f"98{suffix}"


def _gen_bill_acct_no(idx: int) -> str:
    return f"BA{idx:06d}"


def _gen_inv_no(idx: int) -> str:
    return f"INV{idx:09d}"


def _gen_pymt_id(idx: int) -> str:
    return f"P{idx:09d}"


def _gen_cdr_id(idx: int) -> int:
    return idx + 1_000_000_000


def _gen_rtd_id(idx: int) -> int:
    return idx + 2_000_000_000


def _gen_renew_id(idx: int) -> int:
    return idx + 3_000_000_000


# --------------------------------------------------------------------------- #
# Core data structures
# --------------------------------------------------------------------------- #

@dataclass
class Dataset:
    """Container for the generated legacy data set."""
    tables: Mapping[str, list[dict[str, Any]]] = field(default_factory=dict)
    ground_truth: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    pages: Mapping[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Generator implementation
# --------------------------------------------------------------------------- #

def generate(seed: int = 42, n_customers: int = 500) -> Dataset:
    """Generate a deterministic synthetic legacy data set.

    Parameters
    ----------
    seed:
        Seed for :class:`random.Random`.  Using the same seed yields identical
        output.
    n_customers:
        Number of distinct customers to create (each gets at most one contract
        and 1‑2 subscriptions).

    Returns
    -------
    Dataset
        Populated with table rows, ground‑truth leak records, tickets and
        markdown pages.
    """
    rng = random.Random(seed)

    # ------------------------------------------------------------------- #
    # 1. Static reference data – plans, tariffs, discounts
    # ------------------------------------------------------------------- #
    plan_defs = [
        ("NMB_BASIC_199", "Basic 199", 199, 1024, _d("0.05"), 100, _d("0.02")),
        ("NMB_PLUS_399", "Plus 399", 399, 2048, _d("0.04"), 300, _d("0.015")),
        ("NMB_MAX_699", "Max 699", 699, 5120, _d("0.03"), 1000, _d("0.01")),
        ("NMB_BIZ_999", "Biz 999", 999, 10240, _d("0.025"), 2000, _d("0.008")),
        ("NMB_DATA_299", "Data‑only 299", 299, 5120, _d("0.02"), 0, _d("0.00")),
        ("NMB_FAM_899", "Family 899", 899, 8192, _d("0.03"), 1500, _d("0.012")),
    ]

    # Tariff rows per plan / usage type
    usage_types = ("DATA", "VOICE", "SMS")
    tariff_rows: list[dict[str, Any]] = []
    rate_id_seq = 1
    for plan_cd, _, _, inc_mb, data_rt, inc_min, voice_rt in plan_defs:
        # DATA
        tariff_rows.append({
            "RATE_ID": rate_id_seq,
            "PLN_CD": plan_cd,
            "USG_TYP": "DATA",
            "UNIT_RT": data_rt,
            "EFF_FROM": _date(2026, 1, 1),
            "EFF_TO": None,
        })
        rate_id_seq += 1
        # VOICE
        tariff_rows.append({
            "RATE_ID": rate_id_seq,
            "PLN_CD": plan_cd,
            "USG_TYP": "VOICE",
            "UNIT_RT": voice_rt,
            "EFF_FROM": _date(2026, 1, 1),
            "EFF_TO": None,
        })
        rate_id_seq += 1
        # SMS – flat 0.10 INR per SMS for all plans
        tariff_rows.append({
            "RATE_ID": rate_id_seq,
            "PLN_CD": plan_cd,
            "USG_TYP": "SMS",
            "UNIT_RT": _d("0.10"),
            "EFF_FROM": _date(2026, 1, 1),
            "EFF_TO": None,
        })
        rate_id_seq += 1

    # Discounts – ensure two expire on 2026-06-30 and 2026-07-31
    disc_defs = [
        ("DISC10", "10% off", _d("0.10"), _date(2026, 7, 1), _date(2026, 7, 31)),   # expires 2026-07-31
        ("DISC15", "15% off", _d("0.15"), _date(2026, 8, 1), _date(2026, 10, 31)),
        ("DISC5", "5% off", _d("0.05"), _date(2026, 6, 1), _date(2026, 6, 30)),     # expires 2026-06-30
        ("DISC20", "20% off", _d("0.20"), _date(2026, 9, 1), _date(2026, 12, 31)),
    ]

    # ------------------------------------------------------------------- #
    # 2. Core entities – customers, contracts, subscriptions
    # ------------------------------------------------------------------- #
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # CUST_MSTR
    for cust_idx in range(1, n_customers + 1):
        cust_no = f"C{cust_idx:07d}"
        tables["CUST_MSTR"].append({
            "CUST_NO": cust_no,
            "CUST_NM": f"Customer {cust_idx}",
            "CUST_TYP": "R" if rng.random() < 0.8 else "B",
            "CRT_DT": _date(2025, rng.randint(1, 12), rng.randint(1, 28)),
            "STAT_CD": "A",
        })

    # PLAN master (RT_PLAN_CFG)
    for plan_cd, plan_desc, fee, inc_mb, data_rt, inc_min, voice_rt in plan_defs:
        tables["RT_PLAN_CFG"].append({
            "PLN_CD": plan_cd,
            "PLN_DESC": plan_desc,
            "MTHLY_FEE": _d(fee),
            "INCL_DATA_MB": inc_mb,
            "OVG_RT_PER_MB": data_rt,
            "INCL_VOICE_MIN": inc_min,
            "VOICE_RT_PER_MIN": voice_rt,
            "EFF_FROM": _date(2026, 1, 1),
            "EFF_TO": None,
        })

    # TRF_RATE_CFG
    tables["TRF_RATE_CFG"] = tariff_rows

    # DISC_CFG
    for disc_cd, disc_desc, disc_pct, fr, to in disc_defs:
        tables["DISC_CFG"].append({
            "DISC_CD": disc_cd,
            "DISC_DESC": disc_desc,
            "DISC_PCT": disc_pct,
            "VALID_FROM": fr,
            "VALID_TO": to,
        })

    # CONTRACT_TERMS, SUBSCR_MSTR, SUBSCR_DISC
    contract_seq = 1
    subs_seq = 1
    bill_acct_seq = 1

    # Pre‑compute list of first‑of‑month dates between 2025-07-01 and 2026-06-01 inclusive
    start_dates: list[_dt.date] = []
    y, m = 2025, 7
    while (y, m) <= (2026, 6):
        start_dates.append(_date(y, m, 1))
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

    # Window for contract ends that trigger renewal logic
    window_start = _date(2026, 7, 1)
    window_end = _date(2026, 9, 30)

    # We'll store contract info per customer for later use
    cust_contract: dict[str, dict] = {}
    cust_subs: dict[str, list[dict]] = defaultdict(list)

    for cust in tables["CUST_MSTR"]:
        cust_no = cust["CUST_NO"]
        # Pick a plan
        plan = rng.choice(plan_defs)
        plan_cd = plan[0]
        agreed_fee = _d(plan[2])
        # Randomly decide whether a discount applies
        disc = rng.choice(disc_defs + [None])
        disc_cd = disc[0] if disc else None

        # Contract: random start date from start_dates, length 12 months
        start_dt = rng.choice(start_dates)
        # END_DT = start_dt + 12 months - 1 day
        if start_dt.month == 12:
            end_dt = _date(start_dt.year + 1, 1, 1) - _dt.timedelta(days=1)
        else:
            end_dt = _date(start_dt.year, start_dt.month + 1, 1) - _dt.timedelta(days=1)
        # Actually add 12 months: start_dt + 12 months - 1 day
        # Simpler: add 12 months then subtract 1 day
        tmp_year = start_dt.year + (start_dt.month + 11) // 12
        tmp_month = (start_dt.month + 11) % 12 + 1
        end_dt = _date(tmp_year, tmp_month, 1) - _dt.timedelta(days=1)

        auto_renew = "Y" if rng.random() < 0.7 else "N"
        cntr_id = contract_seq
        tables["CONTRACT_TERMS"].append({
            "CNTR_ID": cntr_id,
            "CUST_NO": cust_no,
            "PLN_CD": plan_cd,
            "AGREED_MTHLY_FEE": agreed_fee,
            "DISC_CD": disc_cd,
            "START_DT": start_dt,
            "END_DT": end_dt,
            "AUTO_RENEW_FLG": auto_renew,
        })
        contract_seq += 1
        cust_contract[cust_no] = {
            "CNTR_ID": cntr_id,
            "PLN_CD": plan_cd,
            "AGREED_MTHLY_FEE": agreed_fee,
            "DISC_CD": disc_cd,
            "START_DT": start_dt,
            "END_DT": end_dt,
            "AUTO_RENEW_FLG": auto_renew,
        }

        # Subscriptions – 1 or 2 per contract
        n_subs = rng.choice([1, 2])
        for _ in range(n_subs):
            msisdn = _gen_msisdn(rng)
            bill_acct_no = _gen_bill_acct_no(bill_acct_seq)
            bill_acct_seq += 1
            act_dt = start_dt
            # Determine subscription status based on contract end and auto-renew
            if window_start <= end_dt <= window_end:
                if auto_renew == "Y":
                    prov_stat = "ACTIVE"
                    deact_dt = None
                else:
                    prov_stat = "TERM"
                    deact_dt = end_dt
            else:
                prov_stat = "ACTIVE"
                deact_dt = None

            sub_id = subs_seq
            tables["SUBSCR_MSTR"].append({
                "SUBSCR_ID": sub_id,
                "CUST_NO": cust_no,
                "MSISDN": msisdn,
                "PLN_CD": plan_cd,
                "ACT_DT": act_dt,
                "DEACT_DT": deact_dt,
                "PROV_STAT": prov_stat,
                "BILL_ACCT_NO": bill_acct_no,
            })
            cust_subs[cust_no].append({
                "SUBSCR_ID": sub_id,
                "PLN_CD": plan_cd,
                "ACT_DT": act_dt,
                "DEACT_DT": deact_dt,
                "PROV_STAT": prov_stat,
                "BILL_ACCT_NO": bill_acct_no,
            })
            # Subscription‑level discount (optional)
            if disc and rng.random() < 0.4:
                appl_from = _date(2026, 7, 1)
                appl_to = None
                tables["SUBSCR_DISC"].append({
                    "SUBSCR_ID": sub_id,
                    "DISC_CD": disc_cd,
                    "APPLIED_FROM": appl_from,
                    "APPLIED_TO": appl_to,
                })
            subs_seq += 1

    # ------------------------------------------------------------------- #
    # 3. Renewal logs (RENEW_LOG) – only for auto-renew contracts ending in window
    # ------------------------------------------------------------------- #
    tables["RENEW_LOG"] = []
    for cust_no, ct in cust_contract.items():
        if window_start <= ct["END_DT"] <= window_end and ct["AUTO_RENEW_FLG"] == "Y":
            new_end = _date(ct["END_DT"].year + 1, ct["END_DT"].month, ct["END_DT"].day)
            # Adjust if day doesn't exist (e.g., Feb 29)
            try:
                new_end = _date(ct["END_DT"].year + 1, ct["END_DT"].month, ct["END_DT"].day)
            except ValueError:
                # Last day of next year's same month
                if ct["END_DT"].month == 12:
                    new_end = _date(ct["END_DT"].year + 2, 1, 1) - _dt.timedelta(days=1)
                else:
                    new_end = _date(ct["END_DT"].year + 1, ct["END_DT"].month + 1, 1) - _dt.timedelta(days=1)
            tables["RENEW_LOG"].append({
                "RNW_ID": _gen_renew_id(ct["CNTR_ID"]),
                "CNTR_ID": ct["CNTR_ID"],
                "DUE_DT": ct["END_DT"],
                "RNW_STAT": "DONE",
                "NEW_END_DT": new_end,
            })

    # ------------------------------------------------------------------- #
    # 4. Usage & rating (USG_CDR / RTD_EVT) – only for active periods
    # ------------------------------------------------------------------- #
    cdr_seq = 0
    rtd_seq = 0
    usage_months = ["202607", "202608", "202609"]
    # Helper to check if a subscription is active in a billing period
    def sub_active_in_period(sub: dict, bill_prd: str) -> bool:
        year = int(bill_prd[:4])
        month = int(bill_prd[4:])
        period_start = _date(year, month, 1)
        # subscription active if ACT_DT <= period_start and (DEACT_DT is None or DEACT_DT >= period_start)
        if sub["ACT_DT"] > period_start:
            return False
        return not (sub["DEACT_DT"] is not None and sub["DEACT_DT"] < period_start)

    for cust_no, subs in cust_subs.items():
        for sub in subs:
            sub_id = sub["SUBSCR_ID"]
            plan_cd = sub["PLN_CD"]
            for bill_prd in usage_months:
                if not sub_active_in_period(sub, bill_prd):
                    continue
                year = int(bill_prd[:4])
                month = int(bill_prd[4:])
                days_in_month = calendar.monthrange(year, month)[1]
                n_cdr = rng.randint(5, 15)
                for _ in range(n_cdr):
                    cdr_id = _gen_cdr_id(cdr_seq)
                    cdr_seq += 1
                    usg_typ = rng.choice(usage_types)
                    qty = _d(round(rng.uniform(10, 500), 2))
                    evt_ts = _ts(year, month, rng.randint(1, days_in_month),
                                 rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59))
                    tables["USG_CDR"].append({
                        "CDR_ID": cdr_id,
                        "SUBSCR_ID": sub_id,
                        "USG_TYP": usg_typ,
                        "EVT_TS": evt_ts,
                        "QTY": qty,
                        "RATED_FLG": "Y",
                    })
                    # Rating
                    unit_rt = next(tr["UNIT_RT"] for tr in tariff_rows
                                   if tr["PLN_CD"] == plan_cd and tr["USG_TYP"] == usg_typ)
                    amt = _d(qty * unit_rt)
                    rtd_id = _gen_rtd_id(rtd_seq)
                    rtd_seq += 1
                    tables["RTD_EVT"].append({
                        "RTD_ID": rtd_id,
                        "CDR_ID": cdr_id,
                        "SUBSCR_ID": sub_id,
                        "BILL_PRD": bill_prd,
                        "AMT": amt,
                        "INV_FLG": "Y",
                    })

    # ------------------------------------------------------------------- #
    # 5. Invoicing – BILL_HDR / BILL_DTL
    # ------------------------------------------------------------------- #
    invoice_seq = 1
    line_seq = 1
    # Build mapping from billing account to subscriptions
    acct_to_subs: dict[str, list[dict]] = defaultdict(list)
    for sub in tables["SUBSCR_MSTR"]:
        acct_to_subs[sub["BILL_ACCT_NO"]].append(sub)

    for acct, subs in acct_to_subs.items():
        for bill_prd in usage_months:
            inv_no = _gen_inv_no(invoice_seq)
            invoice_seq += 1
            inv_dt = _date(int(bill_prd[:4]), int(bill_prd[4:]), 10)
            due_dt = inv_dt + _dt.timedelta(days=15)
            # Header placeholder – will fill TOT_AMT later
            tables["BILL_HDR"].append({
                "INV_NO": inv_no,
                "BILL_ACCT_NO": acct,
                "CUST_NO": subs[0]["CUST_NO"],
                "BILL_PRD": bill_prd,
                "INV_DT": inv_dt,
                "TOT_AMT": _d("0.00"),
                "DUE_DT": due_dt,
            })
            line_total = Decimal("0.00")
            for sub in subs:
                if not sub_active_in_period(sub, bill_prd):
                    continue
                cntr = cust_contract[sub["CUST_NO"]]
                recur_amt = cntr["AGREED_MTHLY_FEE"]
                tables["BILL_DTL"].append({
                    "INV_NO": inv_no,
                    "LN_NO": line_seq,
                    "SUBSCR_ID": sub["SUBSCR_ID"],
                    "CHG_TYP": "RECUR",
                    "CHG_REF": cntr["PLN_CD"],
                    "AMT": recur_amt,
                })
                line_seq += 1
                line_total += recur_amt

                # USAGE lines – one per rated event for this month & sub
                for rtd in [r for r in tables["RTD_EVT"]
                            if r["SUBSCR_ID"] == sub["SUBSCR_ID"]
                            and r["BILL_PRD"] == bill_prd]:
                    tables["BILL_DTL"].append({
                        "INV_NO": inv_no,
                        "LN_NO": line_seq,
                        "SUBSCR_ID": sub["SUBSCR_ID"],
                        "CHG_TYP": "USAGE",
                        "CHG_REF": f"RTD:{rtd['RTD_ID']}",
                        "AMT": rtd["AMT"],
                    })
                    line_seq += 1
                    line_total += rtd["AMT"]

                # Discount line if applicable and discount valid for month
                if cntr["DISC_CD"]:
                    disc_cfg = next(d for d in tables["DISC_CFG"]
                                    if d["DISC_CD"] == cntr["DISC_CD"])
                    period_start = _date(int(bill_prd[:4]), int(bill_prd[4:]), 1)
                    if disc_cfg["VALID_FROM"] <= period_start <= disc_cfg["VALID_TO"]:
                        disc_amt = -(recur_amt * disc_cfg["DISC_PCT"]).quantize(_DEC_Q,
                                                                               rounding=ROUND_HALF_UP)
                        tables["BILL_DTL"].append({
                            "INV_NO": inv_no,
                            "LN_NO": line_seq,
                            "SUBSCR_ID": sub["SUBSCR_ID"],
                            "CHG_TYP": "DISC",
                            "CHG_REF": disc_cfg["DISC_CD"],
                            "AMT": disc_amt,
                        })
                        line_seq += 1
                        line_total += disc_amt

            # Update header total
            for hdr in tables["BILL_HDR"]:
                if hdr["INV_NO"] == inv_no:
                    hdr["TOT_AMT"] = line_total.quantize(_DEC_Q, rounding=ROUND_HALF_UP)
                    break

    # ------------------------------------------------------------------- #
    # 6. Payments (PYMT_TXN)
    # ------------------------------------------------------------------- #
    pymt_seq = 1
    for hdr in tables["BILL_HDR"]:
        # 85 % of invoices are paid in full on due date, rest are late or missing
        if rng.random() < 0.85:
            tables["PYMT_TXN"].append({
                "PYMT_ID": _gen_pymt_id(pymt_seq),
                "CUST_NO": hdr["CUST_NO"],
                "REF_INV_NO": hdr["INV_NO"],
                "PYMT_DT": hdr["DUE_DT"],
                "PYMT_AMT": hdr["TOT_AMT"],
                "CHNL": rng.choice(["ONLINE", "UPI", "CASH"]),
            })
            pymt_seq += 1
        elif rng.random() < 0.5:
            # partial or late payment – still link to invoice
            amt = (hdr["TOT_AMT"] * Decimal("0.5")).quantize(_DEC_Q)
            tables["PYMT_TXN"].append({
                "PYMT_ID": _gen_pymt_id(pymt_seq),
                "CUST_NO": hdr["CUST_NO"],
                "REF_INV_NO": hdr["INV_NO"],
                "PYMT_DT": hdr["DUE_DT"] + _dt.timedelta(days=rng.randint(5, 30)),
                "PYMT_AMT": amt,
                "CHNL": rng.choice(["UPI", "CASH"]),
            })
            pymt_seq += 1
        # else: no payment record – will become an unmatched payment leak later

    # ------------------------------------------------------------------- #
    # 7. Ground‑truth leaks – deterministic planting of 8 per type + 2 config_conflict
    # ------------------------------------------------------------------- #
    ground_truth: list[dict[str, Any]] = []
    leak_id_seq = 1
    used_cust_no: set[str] = set()

    def _record_leak(leak_type: str, table: str,
                     rec_ids: list[str],
                     bill_prd: str | None,
                     impact: Decimal,
                     description: str,
                     cust_no: str) -> None:
        nonlocal leak_id_seq
        ground_truth.append({
            "leak_id": f"L{leak_id_seq:03d}",
            "type": leak_type,
            "table": table,
            "record_ids": rec_ids,
            "bill_prd": bill_prd,
            "impact_inr": float(impact.quantize(_DEC_Q)),
            "description": description,
            "cust_no": cust_no,
        })
        leak_id_seq += 1

    # Build helper mappings for leak planting
    cust_to_subs: dict[str, list[dict]] = defaultdict(list)
    for sub in tables["SUBSCR_MSTR"]:
        cust_to_subs[sub["CUST_NO"]].append(sub)

    cust_to_contracts: dict[str, list[dict]] = defaultdict(list)
    for ct in tables["CONTRACT_TERMS"]:
        cust_to_contracts[ct["CUST_NO"]].append(ct)

    cust_to_cdrs: dict[str, list[dict]] = defaultdict(list)
    for cdr in tables["USG_CDR"]:
        sub_id = cdr["SUBSCR_ID"]
        cno = next(s["CUST_NO"] for s in tables["SUBSCR_MSTR"] if s["SUBSCR_ID"] == sub_id)
        cust_to_cdrs[cno].append(cdr)

    cust_to_rtds: dict[str, list[dict]] = defaultdict(list)
    for rtd in tables["RTD_EVT"]:
        sub_id = rtd["SUBSCR_ID"]
        cno = next(s["CUST_NO"] for s in tables["SUBSCR_MSTR"] if s["SUBSCR_ID"] == sub_id)
        cust_to_rtds[cno].append(rtd)

    cust_to_bill_dtls: dict[str, list[dict]] = defaultdict(list)
    for dtl in tables["BILL_DTL"]:
        sub_id = dtl["SUBSCR_ID"]
        cno = next(s["CUST_NO"] for s in tables["SUBSCR_MSTR"] if s["SUBSCR_ID"] == sub_id)
        cust_to_bill_dtls[cno].append(dtl)

    # For each leak type, plant 8 leaks
    leak_types = [
        "unrated_usage",
        "rated_not_invoiced",
        "tariff_mismatch",
        "expired_discount",
        "provisioned_not_billed",
        "missed_renewal",
        "unmatched_payment",
        "duplicate_charge",
    ]

    for leak_type in leak_types:
        planted = 0
        for cno in sorted(cust_to_subs.keys()):
            if planted >= 8:
                break
            if cno in used_cust_no:
                continue
            subs = cust_to_subs[cno]
            cust_to_contracts[cno]
            cdrs = cust_to_cdrs[cno]
            rtds = cust_to_rtds[cno]
            bill_dtls = cust_to_bill_dtls[cno]

            if leak_type == "unrated_usage":
                if not cdrs:
                    continue
                cdr = rng.choice(cdrs)
                cdr["RATED_FLG"] = "N"
                rtds_to_remove = [r for r in tables["RTD_EVT"] if r["CDR_ID"] == cdr["CDR_ID"]]
                for r in rtds_to_remove:
                    tables["RTD_EVT"].remove(r)
                plan_cd = next(sub["PLN_CD"] for sub in subs if sub["SUBSCR_ID"] == cdr["SUBSCR_ID"])
                unit_rt = next(tr["UNIT_RT"] for tr in tariff_rows
                               if tr["PLN_CD"] == plan_cd and tr["USG_TYP"] == cdr["USG_TYP"])
                impact = _d(cdr["QTY"] * unit_rt)
                _record_leak(
                    "unrated_usage",
                    "USG_CDR",
                    [str(cdr["CDR_ID"])],
                    None,
                    impact,
                    f"CDR {cdr['CDR_ID']} was not rated; would have cost INR {impact}",
                    cno,
                )
                planted += 1
                used_cust_no.add(cno)

            elif leak_type == "rated_not_invoiced":
                if not rtds:
                    continue
                rtd = rng.choice(rtds)
                rtd["INV_FLG"] = "N"
                lines = [l for l in tables["BILL_DTL"]
                         if l["CHG_TYP"] == "USAGE" and l["CHG_REF"] == f"RTD:{rtd['RTD_ID']}"]
                for l in lines:
                    tables["BILL_DTL"].remove(l)
                    hdr = next(h for h in tables["BILL_HDR"] if h["INV_NO"] == l["INV_NO"])
                    hdr["TOT_AMT"] = (hdr["TOT_AMT"] - l["AMT"]).quantize(_DEC_Q)
                _record_leak(
                    "rated_not_invoiced",
                    "RTD_EVT",
                    [str(rtd["RTD_ID"])],
                    rtd["BILL_PRD"],
                    rtd["AMT"],
                    f"Rating event {rtd['RTD_ID']} not invoiced; amount INR {rtd['AMT']}",
                    cno,
                )
                planted += 1
                used_cust_no.add(cno)

            elif leak_type == "tariff_mismatch":
                recur_lines = [l for l in bill_dtls if l["CHG_TYP"] == "RECUR"]
                if not recur_lines:
                    continue
                line = rng.choice(recur_lines)
                original = line["AMT"]
                new_amt = (original * Decimal("1.10")).quantize(_DEC_Q)
                line["AMT"] = new_amt
                hdr = next(h for h in tables["BILL_HDR"] if h["INV_NO"] == line["INV_NO"])
                hdr["TOT_AMT"] = (hdr["TOT_AMT"] + (new_amt - original)).quantize(_DEC_Q)
                impact = new_amt - original
                _record_leak(
                    "tariff_mismatch",
                    "BILL_DTL",
                    [f"{line['INV_NO']}:{line['LN_NO']}"],
                    line["INV_NO"][-6:],
                    impact,
                    f"Recurring charge line {line['INV_NO']}:{line['LN_NO']} amount altered from {original} to {new_amt}",
                    cno,
                )
                planted += 1
                used_cust_no.add(cno)

            elif leak_type == "expired_discount":
                # Planting will be done after this loop (see separate planting below)
                # We skip here and handle in dedicated planting step.
                continue

            elif leak_type == "provisioned_not_billed":
                extra_sub_id = max(s["SUBSCR_ID"] for s in tables["SUBSCR_MSTR"]) + 1
                tables["SUBSCR_MSTR"].append({
                    "SUBSCR_ID": extra_sub_id,
                    "CUST_NO": cno,
                    "MSISDN": _gen_msisdn(rng),
                    "PLN_CD": plan_defs[0][0],
                    "ACT_DT": _date(2026, 7, 1),
                    "DEACT_DT": None,
                    "PROV_STAT": "ACTIVE",
                    "BILL_ACCT_NO": None,
                })
                plan_fee = _d(plan_defs[0][2])
                impact = (plan_fee * 3).quantize(_DEC_Q)
                _record_leak(
                    "provisioned_not_billed",
                    "SUBSCR_MSTR",
                    [str(extra_sub_id)],
                    None,
                    impact,
                    f"Active provisioned subscription {extra_sub_id} missing billing account; lost revenue {impact}",
                    cno,
                )
                planted += 1
                used_cust_no.add(cno)

            elif leak_type == "missed_renewal":
                # Planting will be done after this loop (see separate planting below)
                continue

            elif leak_type == "unmatched_payment":
                new_pymt_id = _gen_pymt_id(pymt_seq)
                pymt_seq += 1
                tables["PYMT_TXN"].append({
                    "PYMT_ID": new_pymt_id,
                    "CUST_NO": cno,
                    "REF_INV_NO": None,
                    "PYMT_DT": _date(2026, 8, 20),
                    "PYMT_AMT": _d("1500.00"),
                    "CHNL": "ONLINE",
                })
                _record_leak(
                    "unmatched_payment",
                    "PYMT_TXN",
                    [new_pymt_id],
                    None,
                    _d("1500.00"),
                    "Payment without matching invoice",
                    cno,
                )
                planted += 1
                used_cust_no.add(cno)

            elif leak_type == "duplicate_charge":
                recur_lines = [l for l in bill_dtls if l["CHG_TYP"] == "RECUR"]
                if not recur_lines:
                    continue
                dup_line = rng.choice(recur_lines)
                new_ln_no = line_seq
                line_seq += 1
                tables["BILL_DTL"].append({
                    "INV_NO": dup_line["INV_NO"],
                    "LN_NO": new_ln_no,
                    "SUBSCR_ID": dup_line["SUBSCR_ID"],
                    "CHG_TYP": "RECUR",
                    "CHG_REF": dup_line["CHG_REF"],
                    "AMT": dup_line["AMT"],
                })
                hdr = next(h for h in tables["BILL_HDR"] if h["INV_NO"] == dup_line["INV_NO"])
                hdr["TOT_AMT"] = (hdr["TOT_AMT"] + dup_line["AMT"]).quantize(_DEC_Q)
                _record_leak(
                    "duplicate_charge",
                    "BILL_DTL",
                    [f"{dup_line['INV_NO']}:{new_ln_no}"],
                    dup_line["INV_NO"][-6:],
                    -dup_line["AMT"],
                    f"Duplicate recurring charge line {dup_line['INV_NO']}:{new_ln_no} overbilled by {dup_line['AMT']}",
                    cno,
                )
                planted += 1
                used_cust_no.add(cno)

    # ---------------------- missed_renewal planting (8) ----------------------
    # Pick auto-renew contracts ending in 2026-07 or 2026-08 whose customer is unused
    missed_renewal_planted = 0
    for ct in tables["CONTRACT_TERMS"]:
        if missed_renewal_planted >= 8:
            break
        cno = ct["CUST_NO"]
        if cno in used_cust_no:
            continue
        end_prd = f"{ct['END_DT'].year}{ct['END_DT'].month:02d}"
        if end_prd not in ("202607", "202608"):
            continue
        if ct["AUTO_RENEW_FLG"] != "Y":
            continue
        # Find the RENEW_LOG row for this contract
        rl = next((r for r in tables["RENEW_LOG"] if r["CNTR_ID"] == ct["CNTR_ID"]), None)
        if rl is None:
            continue
        # Change to FAILED
        rl["RNW_STAT"] = "FAILED"
        rl["NEW_END_DT"] = None
        # Subscriptions stay ACTIVE (already are)
        # Remove RECUR lines for this customer's subscriptions in billing periods after END_DT
        impact = Decimal("0.00")
        removed_lines = []
        for sub in cust_subs[cno]:
            sub_id = sub["SUBSCR_ID"]
            # Billing periods after END_DT: we have 202607, 202608, 202609
            for bill_prd in usage_months:
                prd_year = int(bill_prd[:4])
                prd_month = int(bill_prd[4:])
                prd_start = _date(prd_year, prd_month, 1)
                if prd_start > ct["END_DT"]:
                    # Find RECUR lines for this subscription in this invoice
                    inv = next((h for h in tables["BILL_HDR"]
                                if h["BILL_ACCT_NO"] == sub["BILL_ACCT_NO"] and h["BILL_PRD"] == bill_prd), None)
                    if inv:
                        recur_lines = [l for l in tables["BILL_DTL"]
                                       if l["INV_NO"] == inv["INV_NO"] and l["SUBSCR_ID"] == sub_id and l["CHG_TYP"] == "RECUR"]
                        for rl_line in recur_lines:
                            impact += rl_line["AMT"]
                            removed_lines.append(rl_line)
        # Remove the lines and adjust invoice totals
        for rl_line in removed_lines:
            tables["BILL_DTL"].remove(rl_line)
            hdr = next(h for h in tables["BILL_HDR"] if h["INV_NO"] == rl_line["INV_NO"])
            hdr["TOT_AMT"] = (hdr["TOT_AMT"] - rl_line["AMT"]).quantize(_DEC_Q)
        _record_leak(
            "missed_renewal",
            "CONTRACT_TERMS",
            [str(ct["CNTR_ID"])],
            None,
            impact.quantize(_DEC_Q),
            f"Contract {ct['CNTR_ID']} should have auto‑renewed but renewal failed; lost {impact.quantize(_DEC_Q)}",
            cno,
        )
        missed_renewal_planted += 1
        used_cust_no.add(cno)

    # ---------------------- expired_discount planting (8) ----------------------
    expired_discount_planted = 0
    # Discount codes that expire before 2026-08-01 and 2026-09-01
    expired_disc_codes = [d["DISC_CD"] for d in tables["DISC_CFG"]
                          if d["VALID_TO"] < _date(2026, 8, 1)]  # DISC5 (2026-06-30) and DISC10 (2026-07-31)
    for cno in sorted(cust_to_subs.keys()):
        if expired_discount_planted >= 8:
            break
        if cno in used_cust_no:
            continue
        # Find an invoice for this customer in 202608 or 202609
        target_inv = None
        for hdr in tables["BILL_HDR"]:
            if hdr["CUST_NO"] == cno and hdr["BILL_PRD"] in ("202608", "202609"):
                target_inv = hdr
                break
        if target_inv is None:
            continue
        # Pick a discount code that is expired for this period
        period_start = _date(int(target_inv["BILL_PRD"][:4]), int(target_inv["BILL_PRD"][4:]), 1)
        valid_expired = [d for d in expired_disc_codes
                         if next(dc for dc in tables["DISC_CFG"] if dc["DISC_CD"] == d)["VALID_TO"] < period_start]
        if not valid_expired:
            continue
        disc_cd = rng.choice(valid_expired)
        disc_cfg = next(d for d in tables["DISC_CFG"] if d["DISC_CD"] == disc_cd)
        # Compute RECUR total for this invoice
        recur_total = Decimal("0.00")
        for dtl in tables["BILL_DTL"]:
            if dtl["INV_NO"] == target_inv["INV_NO"] and dtl["CHG_TYP"] == "RECUR":
                recur_total += dtl["AMT"]
        if recur_total == 0:
            continue
        disc_amt = -(recur_total * disc_cfg["DISC_PCT"]).quantize(_DEC_Q, rounding=ROUND_HALF_UP)
        # Add new DISC line
        new_ln_no = line_seq
        line_seq += 1
        tables["BILL_DTL"].append({
            "INV_NO": target_inv["INV_NO"],
            "LN_NO": new_ln_no,
            "SUBSCR_ID": subs[0]["SUBSCR_ID"],  # pick first subscription of customer
            "CHG_TYP": "DISC",
            "CHG_REF": disc_cd,
            "AMT": disc_amt,
        })
        # Add SUBSCR_DISC row if missing for that subscription and discount
        sub_id = subs[0]["SUBSCR_ID"]
        existing = next((sd for sd in tables["SUBSCR_DISC"]
                         if sd["SUBSCR_ID"] == sub_id and sd["DISC_CD"] == disc_cd), None)
        if existing is None:
            tables["SUBSCR_DISC"].append({
                "SUBSCR_ID": sub_id,
                "DISC_CD": disc_cd,
                "APPLIED_FROM": period_start,
                "APPLIED_TO": period_start,  # just for that period
            })
        # Recompute invoice total
        target_inv["TOT_AMT"] = (target_inv["TOT_AMT"] + disc_amt).quantize(_DEC_Q)
        impact = abs(disc_amt)
        _record_leak(
            "expired_discount",
            "BILL_DTL",
            [f"{target_inv['INV_NO']}:{new_ln_no}"],
            target_inv["BILL_PRD"],
            impact,
            f"Expired discount {disc_cd} applied on invoice {target_inv['INV_NO']} for period {target_inv['BILL_PRD']}",
            cno,
        )
        expired_discount_planted += 1
        used_cust_no.add(cno)

    # Config-conflict leaks (2) on two more distinct customers
    remaining_customers = [c["CUST_NO"] for c in tables["CUST_MSTR"] if c["CUST_NO"] not in used_cust_no]
    if len(remaining_customers) >= 2:
        c1, c2 = remaining_customers[0], remaining_customers[1]
        used_cust_no.update([c1, c2])
    else:
        c1 = c2 = tables["CUST_MSTR"][0]["CUST_NO"]

    # a) Discount config conflict
    conflict_disc = disc_defs[0][0]  # DISC10
    impact = (_d("0.05") * 50 * 3).quantize(_DEC_Q)
    _record_leak(
        "config_conflict",
        "DISC_CFG",
        [conflict_disc],
        None,
        impact,
        "Discount code DISC10 documented as 10% but configured at 15%; revenue impact estimated.",
        c1,
    )

    # b) Plan fee config conflict
    conflict_plan = "NMB_MAX_699"
    impact = (_d("50.00") * 50 * 2).quantize(_DEC_Q)
    _record_leak(
        "config_conflict",
        "RT_PLAN_CFG",
        [conflict_plan],
        None,
        impact,
        "Plan fee not updated; revenue loss over 2 months for 50 subscriptions.",
        c2,
    )

    # ------------------------------------------------------------------- #
    # 8. Tickets – 12 total (2 conflict + 10 others)
    # ------------------------------------------------------------------- #
    tickets = [
        {
            "key": "NIM-101",
            "source": "jira",
            "type": "Bug",
            "title": "Discount DISC10 applied at 10% but should be 15%",
            "created": _date(2026, 7, 5).isoformat(),
            "description": "Ticket raised after audit; discount percentage mismatch.",
            "labels": ["discount", "config"],
        },
        {
            "key": "NIM-102",
            "source": "ado",
            "type": "Change Request",
            "title": "Increase NMB_MAX_699 fee to 749 from 2026‑08‑01",
            "created": _date(2026, 6, 20).isoformat(),
            "description": "Planned price increase not reflected in RT_PLAN_CFG.",
            "labels": ["plan", "price", "config"],
        },
    ]

    ticket_templates = [
        ("NIM-201", "jira", "Bug", "CDR rating failure for DATA usage", "Some DATA CDRs not rated due to missing tariff.", ["rating", "data"]),
        ("NIM-202", "ado", "Task", "Update billing runbook for new discount", "Documentation update required.", ["docs", "discount"]),
        ("NIM-203", "jira", "Bug", "Invoice total mismatch after discount", "Sum of BILL_DTL lines does not match BILL_HDR.TOT_AMT.", ["billing", "reconciliation"]),
        ("NIM-204", "ado", "Bug", "Payment reconciliation missing for UPI channel", "Payments via UPI not linked to invoices.", ["payment", "upi"]),
        ("NIM-205", "jira", "Story", "Add SMS tariff to TRF_RATE_CFG", "SMS tariff missing for new plan.", ["tariff", "sms"]),
        ("NIM-206", "ado", "Bug", "Renewal log not created for auto-renew contracts", "RENEW_LOG missing for contracts ending in Q3.", ["renewal", "logging"]),
        ("NIM-207", "jira", "Task", "Provisioning system not creating billing accounts", "New subscriptions missing BILL_ACCT_NO.", ["provisioning", "billing"]),
        ("NIM-208", "ado", "Bug", "Duplicate recurring charges on invoice", "Same RECUR line appears twice on invoice.", ["billing", "duplicate"]),
        ("NIM-209", "jira", "Bug", "Expired discount DISC5 still applied in July", "Discount valid only in June but applied later.", ["discount", "expiry"]),
        ("NIM-210", "ado", "Change Request", "Migrate to new tariff engine", "Plan to replace legacy rating logic.", ["tariff", "migration"]),
    ]

    for key, src, typ, title, desc, labels in ticket_templates:
        tickets.append({
            "key": key,
            "source": src,
            "type": typ,
            "title": title,
            "created": _date(2026, rng.randint(7, 9), rng.randint(1, 28)).isoformat(),
            "description": desc,
            "labels": labels,
        })

    # ------------------------------------------------------------------- #
    # 9. Documentation pages (triple-quoted strings)
    # ------------------------------------------------------------------- #
    pages = {
        "plan_catalogue.md": """# Nimbus Telecom Plan Catalogue

## NMB_BASIC_199
- Monthly fee: INR 199
- Included: 1 GB data, 100 min voice

## NMB_PLUS_399
- Monthly fee: INR 399
- Included: 2 GB data, 300 min voice

## NMB_MAX_699
- Monthly fee: INR 699
- Included: 5 GB data, 1,000 min voice

## NMB_BIZ_999
- Monthly fee: INR 999
- Included: 10 GB data, 2,000 min voice

## NMB_DATA_299
- Monthly fee: INR 299
- Included: 5 GB data, 0 min voice

## NMB_FAM_899
- Monthly fee: INR 899
- Included: 8 GB data, 1,500 min voice""",
        "discount_policy.md": """# Discount Policy

- DISC10: 10% off, valid Jul 2026 only
- DISC15: 15% off, valid Aug-Oct 2026
- DISC5: 5% off, June 2026 only
- DISC20: 20% off, Sep-Dec 2026""",
        "billing_runbook.md": """# Billing Run‑Book

1. Generate usage CDRs per subscription.
2. Rate CDRs using tariff rates.
3. Create invoice header per billing account per period.
4. Add recurring, usage and discount lines.
5. Post payments and reconcile.

**Known Issues**:
- Occasionally discounts are applied past expiry (leak).
- Some usage events may not be rated (leak).
- Renewal logs sometimes missing for auto-renew contracts.""",
        "exceptions_register.md": """# Exceptions Register

| Exception ID | Type | Description | Status | Owner | Date Raised |
|--------------|------|-------------|--------|-------|-------------|
| EXC-001 | Unrated Usage | CDR batch for 202607 not rated due to tariff gap | Open | Billing Ops | 2026-07-15 |
| EXC-002 | Rated Not Invoiced | RTD events for subscription 1023 missing from invoice INV000000045 | In Progress | Rating Team | 2026-08-02 |
| EXC-003 | Tariff Mismatch | Plan NMB_MAX_699 recurring charge 10% higher than catalogue | Resolved | Product | 2026-07-20 |
| EXC-004 | Expired Discount | DISC5 applied on invoices for period 202607 | Open | Discount Admin | 2026-07-25 |
| EXC-005 | Provisioned Not Billed | Subscription 5001 active but no billing account assigned | Open | Provisioning | 2026-08-10 |
| EXC-006 | Missed Renewal | Contract 1005 auto-renew failed, 2 months revenue lost | In Progress | Contracts | 2026-08-12 |
| EXC-007 | Unmatched Payment | Payment P000001234 received but no invoice reference | Open | Collections | 2026-08-18 |
| EXC-008 | Duplicate Charge | Invoice INV000000067 has duplicate RECUR line 12 | Resolved | Billing Ops | 2026-08-22 |
| EXC-009 | Config Conflict | Discount DISC10 percentage mismatch (10% vs 15%) | Open | Config Mgmt | 2026-07-05 |
| EXC-010 | Config Conflict | Plan NMB_MAX_699 fee not updated to 749 | In Progress | Product | 2026-06-20 |""",
    }

    # Assemble final dataset
    return Dataset(
        tables=dict(tables),
        ground_truth=ground_truth,
        tickets=tickets,
        pages=pages,
    )


def to_ground_truth_json(ds: Dataset) -> str:
    """Serialise the ground‑truth leak list to pretty‑printed JSON."""
    return json.dumps(ds.ground_truth, indent=2, sort_keys=False, default=str)
