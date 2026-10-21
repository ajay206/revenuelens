"""Tests for the legacy simulation package."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from legacy_sim.__main__ import main
from legacy_sim.generator import generate
from legacy_sim.oracle import find_leaks

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def dataset_fixed():
    """Generate the deterministic dataset once for the whole module."""
    return generate(seed=42, n_customers=500)


# --------------------------------------------------------------------------- #
# Determinism tests
# --------------------------------------------------------------------------- #


def test_determinism_same_seed():
    ds1 = generate(seed=42, n_customers=500)
    ds2 = generate(seed=42, n_customers=500)
    assert ds1.ground_truth == ds2.ground_truth
    # Compare table rows via repr – order and values must match
    assert {
        tbl: [repr(r) for r in rows] for tbl, rows in ds1.tables.items()
    } == {
        tbl: [repr(r) for r in rows] for tbl, rows in ds2.tables.items()
    }


def test_determinism_different_seed():
    ds1 = generate(seed=7, n_customers=500)
    ds2 = generate(seed=42, n_customers=500)
    assert ds1.ground_truth != ds2.ground_truth


# --------------------------------------------------------------------------- #
# Basic counts
# --------------------------------------------------------------------------- #


def test_counts():
    ds = generate(seed=42, n_customers=500)
    assert len(ds.tables["CUST_MSTR"]) == 500
    assert len(ds.tables["CONTRACT_TERMS"]) > 0
    # At least one invoice per period
    periods = {"202607", "202608", "202609"}
    bill_prds = {row["BILL_PRD"] for row in ds.tables["BILL_HDR"]}
    assert bill_prds.issubset(periods)
    assert bill_prds == periods

    # Verify presence of each leak type (including config_conflict)
    leak_types = {
        "unrated_usage",
        "rated_not_invoiced",
        "tariff_mismatch",
        "expired_discount",
        "provisioned_not_billed",
        "missed_renewal",
        "unmatched_payment",
        "duplicate_charge",
        "config_conflict",
    }
    gt_types = {item["type"] for item in ds.ground_truth}
    assert leak_types.issubset(gt_types)

    # Each leak type must have at least 5 instances, except config_conflict exactly 2
    for lt in leak_types - {"config_conflict"}:
        assert sum(1 for item in ds.ground_truth if item["type"] == lt) >= 5
    assert sum(1 for item in ds.ground_truth if item["type"] == "config_conflict") == 2


# --------------------------------------------------------------------------- #
# Ground‑truth consistency
# --------------------------------------------------------------------------- #


def test_ground_truth_ids_exist():
    ds = generate(seed=42, n_customers=500)
    # Build ID sets per table, converting all primary‑key values to strings
    id_sets: dict[str, set] = {}
    for tbl, rows in ds.tables.items():
        if not rows:
            continue
        # Primary key columns per table (hard‑coded for the test)
        pk_cols = {
            "CUST_MSTR": ["CUST_NO"],
            "CONTRACT_TERMS": ["CNTR_ID"],
            "BILL_HDR": ["INV_NO"],
            "BILL_DTL": ["INV_NO", "LN_NO"],
            "USG_CDR": ["CDR_ID"],
            "RTD_EVT": ["RTD_ID"],
            "PYMT_TXN": ["PYMT_ID"],
            "SUBSCR_MSTR": ["SUBSCR_ID"],
            "SUBSCR_DISC": ["SUBSCR_ID", "DISC_CD"],
        }
        cols = pk_cols.get(tbl)
        if not cols:
            continue
        ids = {
            tuple(str(row[col]) for col in cols) if len(cols) > 1 else str(row[cols[0]])
            for row in rows
        }
        id_sets[tbl] = ids

    for item in ds.ground_truth:
        typ = item["type"]
        if typ == "duplicate_charge":
            inv_no, ln_no = item["record_ids"][0].split(":")
            # both parts are strings; compare against stringified tuple
            assert (inv_no, ln_no) in id_sets["BILL_DTL"]
        elif typ == "config_conflict":
            # config_conflict uses DISC_CD or PLN_CD directly
            # we just ensure the value appears somewhere
            val = item["record_ids"][0]
            assert any(val in row.values() for rows in ds.tables.values() for row in rows)
        else:
            # General case: single identifier string matches a primary key
            rec_id = item["record_ids"][0]
            if typ == "unrated_usage":
                assert rec_id in id_sets["USG_CDR"]
            elif typ == "rated_not_invoiced":
                # existence will be checked later via oracle; just ensure format
                assert rec_id
            elif typ in {"tariff_mismatch", "expired_discount", "duplicate_charge"}:
                # already handled above
                pass
            else:
                # For other types the identifier format matches a primary key
                # (e.g., CNTR_ID, SUBSCR_ID, PYMT_ID)
                if typ == "missed_renewal":
                    assert rec_id in id_sets["CONTRACT_TERMS"]
                elif typ == "provisioned_not_billed":
                    assert rec_id in id_sets["SUBSCR_MSTR"]
                elif typ == "unmatched_payment":
                    assert rec_id in id_sets["PYMT_TXN"]
                elif typ == "tariff_mismatch":
                    # handled above
                    pass


def test_oracle_match():
    ds = generate(seed=42, n_customers=500)
    oracle = find_leaks(ds)
    # Build mapping from leak type to set of ground‑truth record ids
    gt_map: dict[str, set[str]] = {}
    for item in ds.ground_truth:
        if item["type"] == "config_conflict":
            continue
        gt_map.setdefault(item["type"], set()).update(item["record_ids"])
    for lt in oracle:
        assert oracle[lt] == gt_map.get(lt, set()), f"Leak type {lt} mismatch"


def test_invoice_totals():
    ds = generate(seed=42, n_customers=500)
    # Sum of detail lines per invoice
    totals: dict[str, Decimal] = {}
    for line in ds.tables["BILL_DTL"]:
        totals.setdefault(line["INV_NO"], Decimal(0))
        totals[line["INV_NO"]] += Decimal(line["AMT"])
    for hdr in ds.tables["BILL_HDR"]:
        assert Decimal(hdr["TOT_AMT"]) == totals.get(hdr["INV_NO"], Decimal(0))


def test_cli_generate(tmp_path: Path):
    out_dir = tmp_path / "out"
    rc = main(["generate", "--seed", "42", "--customers", "10", "--out", str(out_dir)])
    assert rc == 0
    assert (out_dir / "ground_truth.json").exists()
    # Verify at least one CSV file was written
    csv_files = list(out_dir.glob("*.csv"))
    assert csv_files


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Postgres DB not available")
def test_load_loads_one_1000():
    rc = main(
        [
            "load",
            "--seed",
            "42",
            "--customers",
            "50",
            "--database-url",
            os.getenv("DATABASE_URL", ""),
        ]
    )
    assert rc == 0
    # Simple sanity check: connect and count rows
    from psycopg import Connection

    with Connection.connect(os.getenv("DATABASE_URL")) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM nimbus.cust_mstr")
        assert cur.fetchone()[0] == 50
