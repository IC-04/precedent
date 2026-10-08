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
    pdf.set_text_color(38, 48, 51)
    pdf.set_y(24)
    _line(pdf, inv.vendor_legal, 21, "B", 10)
    _line(pdf, inv.vendor_address, 10, gap=6)
    if inv.vendor_tax_id:
        _line(pdf, f"GSTIN: {inv.vendor_tax_id}", 10, gap=6)
    pdf.ln(10)
    pdf.set_draw_color(203, 211, 210)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(10)
    _line(pdf, "INVOICE", 10, "B", 6)
    _line(pdf, inv.invoice_no, 25, "B", 12)
    pdf.ln(6)
    y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(92, 7, "BILL TO")
    pdf.cell(82, 7, "INVOICE DETAILS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(87, 6, inv.bill_to, new_x="LMARGIN", new_y="NEXT")
    left_bottom = pdf.get_y()
    pdf.set_xy(110, y + 7)
    pdf.multi_cell(
        82,
        6,
        f"Invoice date: {inv.issue_date:%d %b %Y}\nDue date: {inv.due_date:%d %b %Y}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_y(max(pdf.get_y(), left_bottom) + 14)
    pdf.set_fill_color(238, 241, 240)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(125, 11, "  DESCRIPTION", fill=True)
    pdf.cell(49, 11, "AMOUNT (INR)  ", align="R", fill=True, new_x="LMARGIN", new_y="NEXT")
    for description, amount in inv.lines:
        y = pdf.get_y()
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(125, 7, description, new_x="LMARGIN", new_y="NEXT")
        bottom = pdf.get_y()
        pdf.set_xy(143, y)
        pdf.cell(49, 7, inr(amount), align="R")
        pdf.set_y(bottom + 8)
        pdf.line(18, pdf.get_y(), 192, pdf.get_y())
        pdf.ln(8)
    total = sum(amount for _, amount in inv.lines)
    pdf.ln(4)
    pdf.set_fill_color(232, 238, 241)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(100, 16, "  Total due", fill=True)
    pdf.cell(74, 16, f"INR {inr(total)}  ", align="R", fill=True, new_x="LMARGIN", new_y="NEXT")
    if inv.notes:
        pdf.ln(14)
        _line(pdf, "NOTES", 10, "B", 7)
        for note in inv.notes:
            _line(pdf, note, 10, gap=6)
            pdf.ln(3)
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
