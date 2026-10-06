"""Real, text-extractable PDFs for invoices, policies and certificates.

Bytes are deterministic: the creation date comes from the world clock and the
producer string is fixed. Core fonts are Latin-1 only, so amounts are written "INR".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from fpdf import FPDF


def inr(minor: int) -> str:
    """Indian digit grouping: 11200000 paise -> '1,12,000'."""
    rupees = minor // 100
    s = str(rupees)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def _doc(created: date) -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_creation_date(datetime(created.year, created.month, created.day, tzinfo=UTC))
    pdf.set_producer("precedent world generator")
    pdf.set_creator("precedent")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)
    return pdf


def _line(pdf: FPDF, text: str, size: int = 10, style: str = "", gap: float = 5.5) -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.multi_cell(0, gap, text, new_x="LMARGIN", new_y="NEXT")


@dataclass
class Invoice:
    vendor_legal: str
    vendor_address: str
    vendor_tax_id: str | None
    invoice_no: str
    issue_date: date
    due_date: date
    bill_to: str
    lines: list[tuple[str, int]]  # (description, amount_minor)
    notes: list[str] = field(default_factory=list)


def write_invoice(path: Path, inv: Invoice) -> None:
    pdf = _doc(inv.issue_date)
    _line(pdf, inv.vendor_legal, 16, "B", 8)
    _line(pdf, inv.vendor_address)
    if inv.vendor_tax_id:
        _line(pdf, f"GSTIN: {inv.vendor_tax_id}")
    pdf.ln(4)
    _line(pdf, f"Invoice {inv.invoice_no}", 14, "B", 7)
    _line(pdf, f"Invoice date: {inv.issue_date:%d %b %Y}")
    _line(pdf, f"Due date: {inv.due_date:%d %b %Y}")
    _line(pdf, f"Bill to: {inv.bill_to}")
    pdf.ln(4)
    for desc, amount in inv.lines:
        _line(pdf, f"{desc}    INR {inr(amount)}")
    total = sum(a for _, a in inv.lines)
    pdf.ln(2)
    _line(pdf, f"Total due: INR {inr(total)}", 12, "B", 7)
    for note in inv.notes:
        pdf.ln(3)
        _line(pdf, note)
    pdf.output(str(path))


def write_document(
    path: Path, title: str, subtitle: str, sections: list[tuple[str, str]], created: date
) -> None:
    """A policy-style document: numbered sections with their text."""
    pdf = _doc(created)
    _line(pdf, title, 16, "B", 8)
    _line(pdf, subtitle, 10, "I")
    pdf.ln(4)
    for number, text in sections:
        _line(pdf, f"{number}  {text}")
        pdf.ln(2)
    pdf.output(str(path))
