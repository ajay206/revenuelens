"""PDF and CSV report generation for RevenueLens findings."""

from __future__ import annotations

import csv
import io

from fpdf import FPDF

from app.reconcile import Finding


def _latin1(s: str) -> str:
    """Convert string to latin-1 safe version for fpdf core fonts."""
    if not s:
        return ""
    s = s.replace("₹", "INR ")
    return s.encode("latin-1", errors="replace").decode("latin-1")


def findings_to_csv(findings: list[Finding]) -> str:
    """Convert findings to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "check",
            "customer_id",
            "period",
            "impact",
            "money",
            "table",
            "record_ids",
            "description",
        ]
    )
    for idx, f in enumerate(findings):
        writer.writerow(
            [
                idx,
                f.check,
                f.customer_id or "",
                f.period or "",
                f.impact,
                abs(f.impact),
                f.table,
                ";".join(f.record_ids),
                f.description,
            ]
        )
    return output.getvalue()


def findings_to_pdf(findings: list[Finding], totals: dict, company_name: str) -> bytes:
    """Generate PDF report from findings."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _latin1(f"RevenueLens leak report - {company_name}"), ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(
        0,
        7,
        _latin1(
            f"Total leaks found: {totals.get('count', 0)} | "
            f"Total INR impact: {totals.get('found_total', 0):,.2f} | "
            f"Latest period: {totals.get('latest_period', 'N/A')} | "
            f"Month INR impact: {totals.get('month_total', 0):,.2f}"
        ),
        ln=True,
    )
    pdf.ln(6)

    # Table header
    pdf.set_font("Helvetica", "B", 9)
    col_widths = [28, 28, 22, 25, 87]  # check, customer, period, amount, description
    headers = ["Check", "Customer", "Period", "INR Amount", "Description"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, _latin1(h), border=1, align="C")
    pdf.ln()

    # Table rows (top 200)
    pdf.set_font("Helvetica", "", 8)
    for f in findings[:200]:
        check = _latin1(f.check)[:25]
        customer = _latin1(f.customer_id or "-")[:25]
        period = _latin1(f.period or "-")[:20]
        amount = _latin1(f"{abs(f.impact):,.2f}")
        desc = _latin1(f.description)[:70]

        pdf.cell(col_widths[0], 6, check, border=1)
        pdf.cell(col_widths[1], 6, customer, border=1)
        pdf.cell(col_widths[2], 6, period, border=1, align="C")
        pdf.cell(col_widths[3], 6, amount, border=1, align="R")
        pdf.cell(col_widths[4], 6, desc, border=1)
        pdf.ln()

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, _latin1(f"Showing top {min(len(findings), 200)} of {len(findings)} findings."), ln=True)

    return bytes(pdf.output())
