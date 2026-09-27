"""Realistic-looking synthetic hospital paperwork for the Live Run sample packs.

documents.py (used by `make seed`) renders deliberately bare PDFs whose exact
text the seeded scenarios and Harbor verifiers depend on — it must not change.
This module is separate: it renders the documents a presenter uploads on the
Live Run page so they look like genuine Indian hospital paperwork (letterhead,
patient block, itemised bill, clinical discharge summary, signatures), while
keeping the facts the backend parses exactly as before:

* bill line-item labels are printed verbatim in their own table cells, so the
  intake agent extracts e.g. "Room rent (semi-private) 3 days @ 4,500" and
  "Registration fee" unchanged (agents/settlement.py matches those strings);
* dates are always printed DD-MM-YYYY, with times in separate fields, because
  settlement._parse_bill_date accepts only DD-MM-YYYY or ISO dates;
* an optional hidden prompt injection is drawn white-on-white on a plain white
  area (never over a tinted fill), invisible when viewed or printed but
  present in the PDF text layer — the attack the poisoned pack demonstrates.

Everything here is fictional: hospitals, people, doctors, registration numbers
(GSTINs carry a deliberately invalid check character), phone numbers and
.example web addresses. Every page carries a grey footer saying so.
"""

from __future__ import annotations

import io
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

SYNTHETIC_NOTICE = "Synthetic document generated for the ClaimGuard demo \u2014 not a real medical record."

PAGE_W, PAGE_H = A4
MARGIN_X = 14 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
FIRST_TOP = 43 * mm  # letterhead height on page 1
LATER_TOP = 25 * mm  # compact running header on later pages
BOTTOM = 21 * mm  # footer

INK = colors.HexColor("#1F2328")
MUTED = colors.HexColor("#5B6670")
FAINT = colors.HexColor("#8C949A")
RULE = colors.HexColor("#C9D1D6")
ZEBRA = colors.HexColor("#F4F7F8")
PANEL = colors.HexColor("#F7F9FA")
PEN_BLUE = colors.HexColor("#1B2A78")
STAMP_BLUE = colors.HexColor("#2B3A9A")


# --- Specs --------------------------------------------------------------------


@dataclass(frozen=True)
class Hospital:
    name: str  # printed in capitals on the letterhead
    tagline: str
    address: str
    phone: str
    emergency_phone: str
    email: str
    website: str
    gstin: str
    registration_no: str  # clinical establishment registration
    emblem: str = "sunrise"  # "sunrise" | "lake"
    primary: str = "#0E5A6B"
    accent: str = "#E8892B"


@dataclass(frozen=True)
class Patient:
    salutation: str  # "Ms." / "Mr."
    name: str
    age: int
    sex: str
    uhid: str
    address_masked: str
    mobile_masked: str

    @property
    def display_name(self) -> str:
        return f"{self.salutation} {self.name}"


@dataclass(frozen=True)
class Doctor:
    name: str  # "Dr. ..."
    qualifications: str
    designation: str
    department: str
    registration_no: str


@dataclass(frozen=True)
class Stay:
    ip_no: str
    admission_date: date
    admission_time: str  # "14:35"
    discharge_date: date
    discharge_time: str
    ward: str
    bed: str
    admitted_via: str
    consultant: Doctor
    insurer: str
    policy_number: str
    member_id: str


@dataclass(frozen=True)
class BillLine:
    description: str  # printed verbatim — the intake agent reads it as the line-item label
    code: str  # SAC / HSN
    qty: int
    rate: float
    amount: float


@dataclass(frozen=True)
class Payment:
    receipt_no: str
    mode: str
    reference: str
    amount: float


@dataclass
class FinalBillSpec:
    hospital: Hospital
    patient: Patient
    stay: Stay
    bill_no: str
    bill_time: str  # time the final bill was generated, on the discharge date
    lines: list[BillLine]
    total: float
    payments: list[Payment]
    prepared_by: str
    checked_by: str
    printed_by: str = "BILL03"

    def __post_init__(self) -> None:
        for line in self.lines:
            if abs(line.qty * line.rate - line.amount) > 0.005:
                raise ValueError(f"bill line {line.description!r}: {line.qty} x {line.rate} != {line.amount}")
        if abs(sum(line.amount for line in self.lines) - self.total) > 0.005:
            raise ValueError(f"bill lines do not add up to the total {self.total}")
        if abs(sum(p.amount for p in self.payments) - self.total) > 0.005:
            raise ValueError("payments do not settle the bill")


@dataclass(frozen=True)
class LabRow:
    parameter: str
    values: tuple[str, ...]  # one per DischargeSummarySpec.lab_days entry ("" = not done)
    reference: str


@dataclass(frozen=True)
class Medication:
    medicine: str
    dose: str
    route: str
    frequency: str
    duration: str


@dataclass
class DischargeSummarySpec:
    hospital: Hospital
    patient: Patient
    stay: Stay
    final_diagnosis: str
    icd10: str
    presenting_complaints: list[str]
    history_of_present_illness: str
    past_history: str
    allergies: str
    personal_history: str
    admission_vitals: list[tuple[str, str]]
    general_examination: str
    systemic_examination: list[tuple[str, str]]
    lab_days: tuple[int, ...]  # day offsets from admission, one table column each
    lab_rows: list[LabRow]
    other_investigations: list[tuple[str, str]]
    course_in_hospital: str
    treatment_given: list[str]
    condition_at_discharge: str
    discharge_vitals: str
    medications: list[Medication]
    advice: list[str]
    warning_signs: str
    follow_up: str
    prepared_by: str
    procedures: str = "Nil"
    discharge_type: str = "Routine discharge, as advised by the treating consultant"
    hidden_injection: list[str] | None = field(default=None)

    def __post_init__(self) -> None:
        for row in self.lab_rows:
            if len(row.values) != len(self.lab_days):
                raise ValueError(f"lab row {row.parameter!r} has {len(row.values)} values for {len(self.lab_days)} days")


# --- Fonts ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Fonts:
    sans: str
    bold: str
    italic: str
    serif_bold: str
    rupee: str


def _font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    dirs += [Path(p) for p in (
        "/usr/share/fonts/truetype/msttcorefonts", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF",
        "/Library/Fonts", "/System/Library/Fonts/Supplemental",
    )]
    return [d for d in dirs if d.is_dir()]


def _find(names: tuple[str, ...]) -> list[Path] | None:
    for directory in _font_dirs():
        paths = [directory / n for n in names]
        if all(p.is_file() for p in paths):
            return paths
    return None


@lru_cache(maxsize=1)
def _fonts() -> _Fonts:
    """Arial (or DejaVu Sans) embedded when available — both carry the rupee
    sign U+20B9. Without either, the built-in Helvetica family is used and
    amounts are marked "Rs." instead (Helvetica has no rupee glyph)."""
    sans_sets = (
        ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
        ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
        ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    )
    sans = bold = italic = None
    rupee = "Rs."
    for names in sans_sets:
        paths = _find(names)
        if not paths:
            continue
        try:
            faces = [TTFont(f"CGDoc{suffix}", str(p)) for suffix, p in zip(("", "-Bold", "-Italic", "-BoldItalic"), paths)]
        except Exception:  # noqa: BLE001 - unreadable font file: try the next family
            continue
        for face in faces:
            pdfmetrics.registerFont(face)
        pdfmetrics.registerFontFamily("CGDoc", normal="CGDoc", bold="CGDoc-Bold", italic="CGDoc-Italic", boldItalic="CGDoc-BoldItalic")
        sans, bold, italic = "CGDoc", "CGDoc-Bold", "CGDoc-Italic"
        if all(0x20B9 in face.face.charToGlyph for face in faces):
            rupee = "\u20b9"
        break
    if sans is None:
        sans, bold, italic = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

    serif_bold = "Times-Bold"
    for names in (("georgiab.ttf",), ("Georgia Bold.ttf",), ("DejaVuSerif-Bold.ttf",)):
        paths = _find(names)
        if paths:
            try:
                pdfmetrics.registerFont(TTFont("CGDocSerif-Bold", str(paths[0])))
                serif_bold = "CGDocSerif-Bold"
                break
            except Exception:  # noqa: BLE001
                continue
    return _Fonts(sans=sans, bold=bold, italic=italic, serif_bold=serif_bold, rupee=rupee)


def _t(text: str) -> str:
    """Plain text for canvas drawing, with the rupee sign swapped for "Rs."
    when the fallback font cannot draw it."""
    f = _fonts()
    return text if f.rupee == "\u20b9" else text.replace("\u20b9 ", "Rs. ").replace("\u20b9", "Rs.")


def _x(text: str) -> str:
    """Escaped text for a Paragraph."""
    return escape(_t(text))


# --- Formatting ---------------------------------------------------------------


def inr(amount: float, decimals: int = 2) -> str:
    """Indian digit grouping: 138500.0 -> "1,38,500.00"."""
    negative = amount < 0
    whole, _, frac = f"{abs(amount):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return ("-" if negative else "") + whole + (f".{frac}" if decimals else "")


_ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _below_hundred(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else ""))


def _words(n: int) -> str:
    """Indian numbering (thousand, lakh, crore)."""
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, n = divmod(n, 100)
    if crore:
        parts.append(f"{_words(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if hundred:
        parts.append(f"{_ONES[hundred]} Hundred")
    if n:
        parts.append(_below_hundred(n))
    return " ".join(parts)


def rupees_in_words(amount: float) -> str:
    paise_total = round(amount * 100)
    rupees, paise = divmod(paise_total, 100)
    text = f"Rupees {_words(rupees)}"
    if paise:
        text += f" and {_below_hundred(paise)} Paise"
    return text + " Only"


def _d(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# --- Styles -------------------------------------------------------------------


def _styles(primary: colors.Color) -> dict[str, ParagraphStyle]:
    f = _fonts()
    base = ParagraphStyle("base", fontName=f.sans, fontSize=8.4, leading=10.9, textColor=INK, alignment=TA_LEFT)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.4, leading=9.6),
        "muted": ParagraphStyle("muted", parent=base, fontSize=7.3, leading=9.4, textColor=MUTED),
        "label": ParagraphStyle("label", parent=base, fontSize=7.4, leading=9.8, textColor=MUTED),
        "value": ParagraphStyle("value", parent=base, fontSize=8.3, leading=10.4),
        "value_b": ParagraphStyle("value_b", parent=base, fontName=f.bold, fontSize=8.4, leading=10.4),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.1, leading=10.2),
        "cell_r": ParagraphStyle("cell_r", parent=base, fontSize=8.1, leading=10.2, alignment=TA_RIGHT),
        "cell_c": ParagraphStyle("cell_c", parent=base, fontSize=8.1, leading=10.2, alignment=TA_CENTER),
        "head": ParagraphStyle("head", parent=base, fontName=f.bold, fontSize=7.6, leading=9.4, textColor=colors.white),
        "head_r": ParagraphStyle("head_r", parent=base, fontName=f.bold, fontSize=7.6, leading=9.4, textColor=colors.white, alignment=TA_RIGHT),
        "head_c": ParagraphStyle("head_c", parent=base, fontName=f.bold, fontSize=7.6, leading=9.4, textColor=colors.white, alignment=TA_CENTER),
        "thead": ParagraphStyle("thead", parent=base, fontName=f.bold, fontSize=7.5, leading=9.2, textColor=INK),
        "thead_c": ParagraphStyle("thead_c", parent=base, fontName=f.bold, fontSize=7.5, leading=9.2, textColor=INK, alignment=TA_CENTER),
        "section": ParagraphStyle("section", parent=base, fontName=f.bold, fontSize=8.3, leading=10, textColor=primary),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=11, bulletIndent=2, spaceAfter=0.6),
        "sig": ParagraphStyle("sig", parent=base, fontSize=7.6, leading=9.8, alignment=TA_CENTER),
        "sig_b": ParagraphStyle("sig_b", parent=base, fontName=f.bold, fontSize=8, leading=10, alignment=TA_CENTER),
        "note": ParagraphStyle("note", parent=base, fontSize=6.9, leading=8.9, textColor=MUTED),
        "total_l": ParagraphStyle("total_l", parent=base, fontSize=8.3, leading=10.4),
        "total_r": ParagraphStyle("total_r", parent=base, fontSize=8.3, leading=10.4, alignment=TA_RIGHT),
        "total_lb": ParagraphStyle("total_lb", parent=base, fontName=f.bold, fontSize=8.8, leading=11),
        "total_rb": ParagraphStyle("total_rb", parent=base, fontName=f.bold, fontSize=8.8, leading=11, alignment=TA_RIGHT),
        "diag": ParagraphStyle("diag", parent=base, fontName=f.bold, fontSize=9.2, leading=12),
    }


# --- Drawing helpers ------------------------------------------------------------


def _emblem(c, kind: str, cx: float, cy: float, r: float, primary: colors.Color, accent: colors.Color) -> None:
    """A simple drawn logo: a roundel with a rising sun or a lake and a cross."""
    c.saveState()
    c.setFillColor(primary)
    c.circle(cx, cy, r, stroke=0, fill=1)
    c.setStrokeColor(colors.white)
    c.setLineWidth(max(r * 0.05, 0.5))
    c.circle(cx, cy, r * 0.86, stroke=1, fill=0)
    c.setLineCap(1)
    if kind == "sunrise":
        hy = cy - r * 0.2
        c.setStrokeColor(accent)
        c.setLineWidth(r * 0.075)
        for deg in (18, 45, 72, 90, 108, 135, 162):
            a = math.radians(deg)
            c.line(cx + math.cos(a) * r * 0.47, hy + math.sin(a) * r * 0.47, cx + math.cos(a) * r * 0.66, hy + math.sin(a) * r * 0.66)
        c.setFillColor(accent)
        c.wedge(cx - r * 0.38, hy - r * 0.38, cx + r * 0.38, hy + r * 0.38, 0, 180, stroke=0, fill=1)
        c.setFillColor(colors.white)
        arm, half = r * 0.055, r * 0.17
        c.rect(cx - arm, hy + r * 0.05, 2 * arm, 2 * half, stroke=0, fill=1)
        c.rect(cx - half, hy + r * 0.05 + half - arm, 2 * half, 2 * arm, stroke=0, fill=1)
        c.setStrokeColor(colors.white)
        c.setLineWidth(r * 0.06)
        c.line(cx - r * 0.6, hy, cx + r * 0.6, hy)
        c.setLineWidth(r * 0.05)
        c.line(cx - r * 0.44, hy - r * 0.17, cx + r * 0.44, hy - r * 0.17)
        c.line(cx - r * 0.28, hy - r * 0.32, cx + r * 0.28, hy - r * 0.32)
    else:  # lake
        c.setFillColor(colors.white)
        arm, half = r * 0.085, r * 0.27
        top = cy + r * 0.12
        c.rect(cx - arm, top, 2 * arm, 2 * half, stroke=0, fill=1)
        c.rect(cx - half, top + half - arm, 2 * half, 2 * arm, stroke=0, fill=1)
        for k, (width, colour) in enumerate(((0.62, accent), (0.52, colors.white), (0.38, accent))):
            y = cy - r * (0.08 + 0.19 * k)
            w = r * width
            p = c.beginPath()
            p.moveTo(cx - w, y)
            steps = 4
            for i in range(steps):
                x0 = cx - w + 2 * w * i / steps
                x1 = cx - w + 2 * w * (i + 1) / steps
                amp = r * 0.07 * (1 if i % 2 == 0 else -1)
                p.curveTo(x0 + (x1 - x0) * 0.3, y + amp, x0 + (x1 - x0) * 0.7, y + amp, x1, y)
            c.setStrokeColor(colour)
            c.setLineWidth(r * 0.07)
            c.drawPath(p, stroke=1, fill=0)
    c.restoreState()


def _fit_size(text: str, font: str, max_size: float, max_width: float, char_space: float = 0) -> float:
    size = max_size
    while size > max_size * 0.6 and pdfmetrics.stringWidth(text, font, size) + char_space * len(text) > max_width:
        size -= 0.25
    return size


def _draw_spaced(c, text: str, x: float, y: float, font: str, size: float, char_space: float) -> None:
    t = c.beginText(x, y)
    t.setFont(font, size)
    t.setCharSpace(char_space)
    t.textOut(text)
    t.setCharSpace(0)  # character spacing is page text state: reset it, or later text inherits it
    c.drawText(t)


def _letterhead(c, h: Hospital) -> None:
    f = _fonts()
    primary, accent = colors.HexColor(h.primary), colors.HexColor(h.accent)
    c.saveState()
    c.setFillColor(primary)
    c.rect(0, PAGE_H - 3.2 * mm, PAGE_W, 3.2 * mm, stroke=0, fill=1)
    c.setFillColor(accent)
    c.rect(0, PAGE_H - 4.1 * mm, PAGE_W, 0.9 * mm, stroke=0, fill=1)

    r = 10.5 * mm
    _emblem(c, h.emblem, MARGIN_X + r, PAGE_H - 22.5 * mm, r, primary, accent)

    x0 = MARGIN_X + 2 * r + 5 * mm
    right = PAGE_W - MARGIN_X
    name = h.name.upper()
    size = _fit_size(name, f.serif_bold, 19, right - x0, char_space=0.6)
    c.setFillColor(primary)
    _draw_spaced(c, name, x0, PAGE_H - 16.8 * mm, f.serif_bold, size, 0.6)
    c.setFillColor(MUTED)
    c.setFont(f.italic, 7.6)
    c.drawString(x0, PAGE_H - 21.6 * mm, _t(h.tagline))

    c.setFillColor(INK)
    c.setFont(f.sans, 7.6)
    left_lines = [h.address, f"Tel: {h.phone}   \u00b7   24x7 Emergency: {h.emergency_phone}", f"E-mail: {h.email}   \u00b7   Web: {h.website}"]
    for i, line in enumerate(left_lines):
        c.drawString(x0, PAGE_H - (26.6 + 3.8 * i) * mm, _t(line))
    right_lines = [("GSTIN", h.gstin), ("Clinical Estt. Regn.", h.registration_no)]
    for i, (label, value) in enumerate(right_lines):
        y = PAGE_H - (26.6 + 3.8 * i) * mm
        c.setFont(f.bold, 7.6)
        c.drawRightString(right, y, value)
        c.setFont(f.sans, 7.6)
        c.setFillColor(MUTED)
        c.drawRightString(right - pdfmetrics.stringWidth(value, f.bold, 7.6) - 1.5 * mm, y, f"{label}:")
        c.setFillColor(INK)

    c.setStrokeColor(primary)
    c.setLineWidth(1.1)
    c.line(MARGIN_X, PAGE_H - 39 * mm, right, PAGE_H - 39 * mm)
    c.setStrokeColor(accent)
    c.setLineWidth(0.45)
    c.line(MARGIN_X, PAGE_H - 39.9 * mm, right, PAGE_H - 39.9 * mm)
    c.restoreState()


def _running_header(c, h: Hospital, doc_title: str, right_top: str, right_bottom: str) -> None:
    f = _fonts()
    primary, accent = colors.HexColor(h.primary), colors.HexColor(h.accent)
    c.saveState()
    c.setFillColor(primary)
    c.rect(0, PAGE_H - 3.2 * mm, PAGE_W, 3.2 * mm, stroke=0, fill=1)
    c.setFillColor(accent)
    c.rect(0, PAGE_H - 4.1 * mm, PAGE_W, 0.9 * mm, stroke=0, fill=1)
    r = 5.2 * mm
    _emblem(c, h.emblem, MARGIN_X + r, PAGE_H - 13.4 * mm, r, primary, accent)
    x0 = MARGIN_X + 2 * r + 3.5 * mm
    c.setFillColor(primary)
    _draw_spaced(c, h.name.upper(), x0, PAGE_H - 12.6 * mm, f.serif_bold, 10.5, 0.35)
    c.setFillColor(MUTED)
    c.setFont(f.sans, 7.4)
    c.drawString(x0, PAGE_H - 16.6 * mm, _t(doc_title))
    right = PAGE_W - MARGIN_X
    c.setFillColor(INK)
    c.setFont(f.bold, 7.6)
    c.drawRightString(right, PAGE_H - 12.6 * mm, _t(right_top))
    c.setFont(f.sans, 7.4)
    c.setFillColor(MUTED)
    c.drawRightString(right, PAGE_H - 16.6 * mm, _t(right_bottom))
    c.setStrokeColor(primary)
    c.setLineWidth(0.8)
    c.line(MARGIN_X, PAGE_H - 20.5 * mm, right, PAGE_H - 20.5 * mm)
    c.restoreState()


def _footer(c, left: str, page: int, total: int | None) -> None:
    f = _fonts()
    c.saveState()
    right = PAGE_W - MARGIN_X
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.line(MARGIN_X, 16.5 * mm, right, 16.5 * mm)
    c.setFillColor(MUTED)
    c.setFont(f.sans, 6.9)
    c.drawString(MARGIN_X, 12.8 * mm, _t(left))
    c.drawRightString(right, 12.8 * mm, f"Page {page} of {total or page}")
    c.setFillColor(FAINT)
    c.setFont(f.sans, 6.3)
    c.drawCentredString(PAGE_W / 2, 8.6 * mm, _t(SYNTHETIC_NOTICE))
    c.restoreState()


def _scribble(c, x: float, y: float, w: float, h: float, seed: str, ink: colors.Color = PEN_BLUE) -> None:
    """A pen signature: a smooth curve through a tall capital loop, a run of
    cursive humps with a looped ascender or two, a tail, and an underline."""
    rnd = random.Random(seed)
    pts = [(0.0, 0.32), (0.04, 0.9), (0.1, 1.0), (0.12, 0.6), (0.07, 0.14), (0.02, 0.3), (0.13, 0.42)]
    px = 0.15
    n = rnd.randint(5, 7)
    ascenders = set(rnd.sample(range(1, n), 2))
    for i in range(n):
        step = rnd.uniform(0.075, 0.1)
        if i in ascenders:
            pts += [(px + step * 0.6, rnd.uniform(0.85, 0.98)), (px + step * 0.3, rnd.uniform(0.7, 0.8)), (px + step * 0.55, 0.18)]
        else:
            pts += [(px + step * 0.35, rnd.uniform(0.45, 0.62)), (px + step * 0.7, rnd.uniform(0.16, 0.26))]
        px += step
    pts += [(px + 0.05, 0.5), (px + 0.1, 0.42)]
    span = px + 0.1
    pts = [(x + (u + (v - 0.3) * 0.1) / span * w, y + v * h) for u, v in pts]

    c.saveState()
    c.setStrokeColor(ink)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.setLineWidth(0.8)
    path = c.beginPath()
    path.moveTo(*pts[0])
    for i in range(len(pts) - 1):  # Catmull-Rom spline as cubic Beziers
        p0, p1, p2 = pts[max(i - 1, 0)], pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        path.curveTo(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                     p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, p2[0], p2[1])
    c.drawPath(path, stroke=1, fill=0)
    under = c.beginPath()
    under.moveTo(x + 0.12 * w, y + 0.06 * h)
    under.curveTo(x + 0.4 * w, y - 0.06 * h, x + 0.75 * w, y + 0.0 * h, x + 0.98 * w, y + 0.16 * h)
    c.setLineWidth(0.65)
    c.drawPath(under, stroke=1, fill=0)
    c.restoreState()


class _Signature(Flowable):
    """Signature area: a pen scribble, optionally under a rubber stamp."""

    def __init__(self, width: float, height: float, seed: str, stamp: tuple[str, ...] | None = None, stamp_kind: str = "paid"):
        super().__init__()
        self.width, self.height = width, height
        self.seed, self.stamp, self.stamp_kind = seed, stamp, stamp_kind

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        c = self.canv
        f = _fonts()
        w, h = self.width, self.height
        if self.stamp:
            c.saveState()
            if self.stamp_kind == "paid":
                sw, sh = min(w * 0.6, 44 * mm), 15 * mm
                c.translate(sw / 2 + 1 * mm, h * 0.55)
                c.rotate(6)
            else:
                sw, sh = min(w * 0.64, 46 * mm), 13 * mm
                c.translate(sw / 2 + 1 * mm, h * 0.45)
                c.rotate(-3)
            c.setStrokeColor(STAMP_BLUE)
            c.setFillColor(STAMP_BLUE)
            c.setStrokeAlpha(0.75)
            c.setFillAlpha(0.75)
            c.setLineWidth(1.3)
            c.roundRect(-sw / 2, -sh / 2, sw, sh, 3, stroke=1, fill=0)
            c.setLineWidth(0.5)
            c.roundRect(-sw / 2 + 1.8, -sh / 2 + 1.8, sw - 3.6, sh - 3.6, 2, stroke=1, fill=0)
            if self.stamp_kind == "paid":
                top, big, bottom = self.stamp
                c.setFont(f.bold, _fit_size(top, f.bold, 5.6, sw - 8))
                c.drawCentredString(0, sh / 2 - 7.2, _t(top))
                c.setFont(f.bold, 15)
                _draw_spaced(c, big, -(pdfmetrics.stringWidth(big, f.bold, 15) + 2.5 * len(big)) / 2 + 1.2, -5.2, f.bold, 15, 2.5)
                c.setFont(f.bold, 5.8)
                c.drawCentredString(0, -sh / 2 + 5, _t(bottom))
            else:
                for i, line in enumerate(self.stamp):
                    font = f.bold if i == 0 else f.sans
                    size = _fit_size(line, font, 6.8 if i == 0 else 6, sw - 14)
                    c.setFont(font, size)
                    c.drawCentredString(0, sh / 2 - 10 - i * 8.2, _t(line))
            c.restoreState()
        # The signature overlaps the stamp's right edge, as a pen signature usually does.
        sig_w = min(w * (0.42 if self.stamp_kind == "doctor" else 0.46), 32 * mm)
        _scribble(c, w - sig_w - 1 * mm, h * 0.2, sig_w, h * 0.6, self.seed)


class _SpacedTitle(Flowable):
    def __init__(self, text: str, size: float, colour: colors.Color, char_space: float = 1.6):
        super().__init__()
        self.text, self.size, self.colour, self.char_space = text, size, colour, char_space

    def wrap(self, avail_w, avail_h):
        self.avail_w = avail_w
        return avail_w, self.size * 1.25

    def draw(self):
        f = _fonts()
        width = pdfmetrics.stringWidth(self.text, f.bold, self.size) + self.char_space * (len(self.text) - 1)
        self.canv.setFillColor(self.colour)
        _draw_spaced(self.canv, self.text, (self.avail_w - width) / 2, self.size * 0.28, f.bold, self.size, self.char_space)


class _HiddenText(Flowable):
    """White text on the plain white page: invisible when viewed or printed,
    still in the PDF text layer. Takes its own vertical space so nothing
    tinted is ever drawn underneath it."""

    def __init__(self, lines: list[str], size: float = 7):
        super().__init__()
        self.lines, self.size = lines, size

    def wrap(self, avail_w, avail_h):
        return avail_w, len(self.lines) * self.size * 1.35 + 4

    def draw(self):
        f = _fonts()
        c = self.canv
        c.saveState()
        c.setFillColorRGB(1, 1, 1)
        c.setFont(f.sans, self.size)
        y = len(self.lines) * self.size * 1.35 - self.size + 2
        for line in self.lines:
            c.drawString(0, y, line)
            y -= self.size * 1.35
        c.restoreState()


def _barcode(value: str, caption: str, styles) -> list:
    bc = code128.Code128(value, barHeight=8.5 * mm, barWidth=0.62, quiet=0, humanReadable=0)
    return [bc, Spacer(1, 1), Paragraph(_x(caption), ParagraphStyle("bc", parent=styles["muted"], alignment=TA_RIGHT, fontSize=6.8, leading=8))]


def _qr(value: str, size: float) -> Drawing:
    widget = QrCodeWidget(value, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    d = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    d.add(widget)
    return d


def _section(title: str, styles, primary: colors.Color) -> Table:
    t = Table([[Paragraph(_x(title.upper()), styles["section"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, primary),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
    ]))
    return t


def _kv_block(rows: list[tuple[str, str, str, str]], styles, col_widths: list[float], full_rows: list[tuple[str, str]] = (),
              bold_values: set[str] = frozenset()) -> Table:
    """The boxed patient / admission details grid."""
    data = []
    for l1, v1, l2, v2 in rows:
        data.append([
            Paragraph(_x(l1), styles["label"]), Paragraph(_x(v1), styles["value_b" if l1 in bold_values else "value"]),
            Paragraph(_x(l2), styles["label"]), Paragraph(_x(v2), styles["value_b" if l2 in bold_values else "value"]),
        ])
    spans = []
    for label, value in full_rows:
        spans.append(len(data))
        data.append([Paragraph(_x(label), styles["label"]), Paragraph(_x(value), styles["value"]), "", ""])
    t = Table(data, colWidths=col_widths)
    style = [
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBEFORE", (2, 0), (2, len(rows) - 1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("TOPPADDING", (0, 0), (-1, 0), 4), ("BOTTOMPADDING", (0, -1), (-1, -1), 4),
    ]
    for r in spans:
        style += [("SPAN", (1, r), (3, r)), ("LINEABOVE", (0, r), (-1, r), 0.4, RULE), ("TOPPADDING", (0, r), (-1, r), 3)]
    t.setStyle(TableStyle(style))
    return t


def _title_row(left: list, title: str, right: list, primary: colors.Color) -> Table:
    t = Table([[left, _SpacedTitle(title, 12.5, primary), right]], colWidths=[52 * mm, CONTENT_W - 104 * mm, 52 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


# --- Document assembly ------------------------------------------------------------


def _build(path: Path, story_factory, *, hospital: Hospital, running_title: str, running_right: tuple[str, str],
           footer_left: str, meta_title: str, meta_subject: str) -> None:
    """Two passes: the first counts pages so the footer can say "Page n of N"."""

    def render(target, total: int | None) -> int:
        pages = {"n": 0}

        def on_first(c, doc):
            pages["n"] = c.getPageNumber()
            _letterhead(c, hospital)
            _footer(c, footer_left, c.getPageNumber(), total)

        def on_later(c, doc):
            pages["n"] = c.getPageNumber()
            _running_header(c, hospital, running_title, *running_right)
            _footer(c, footer_left, c.getPageNumber(), total)

        doc = BaseDocTemplate(
            target, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=LATER_TOP, bottomMargin=BOTTOM,
            title=meta_title, author=f"{hospital.name} (synthetic)", subject=meta_subject,
            creator="ClaimGuard synthetic document generator", producer="ClaimGuard demo (ReportLab)",
        )
        first = Frame(MARGIN_X, BOTTOM, CONTENT_W, PAGE_H - FIRST_TOP - BOTTOM, id="first", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        later = Frame(MARGIN_X, BOTTOM, CONTENT_W, PAGE_H - LATER_TOP - BOTTOM, id="later", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate("first", [first], onPage=on_first), PageTemplate("later", [later], onPage=on_later)])
        doc.build([NextPageTemplate("later"), *story_factory()])
        return pages["n"]

    total = render(io.BytesIO(), None)
    render(str(path), total)


def render_final_bill(path: Path | str, spec: FinalBillSpec) -> Path:
    path = Path(path)
    h, p, s = spec.hospital, spec.patient, spec.stay
    primary, accent = colors.HexColor(h.primary), colors.HexColor(h.accent)
    st = _styles(primary)
    f = _fonts()
    rupee = f.rupee
    los = (s.discharge_date - s.admission_date).days

    def story():
        out = []
        left = [
            Paragraph(_x("Bill Type: Final (In-patient)"), st["muted"]),
            Paragraph(_x("Category: Self-paying \u00b7 Reimbursement"), st["muted"]),
            Paragraph("<b>ORIGINAL</b> \u2014 Patient copy", st["muted"]),
        ]
        out.append(_title_row(left, "IN-PATIENT FINAL BILL", _barcode(spec.bill_no, spec.bill_no, st), primary))
        out.append(Spacer(1, 3.2 * mm))

        c = s.consultant
        out.append(_kv_block(
            [
                ("Patient Name", p.display_name, "Bill No.", spec.bill_no),
                ("Age / Sex", f"{p.age} Y / {p.sex}", "Bill Date", _d(s.discharge_date)),
                ("UHID", p.uhid, "Admission Date", _d(s.admission_date)),
                ("IP No.", s.ip_no, "Admission Time", f"{s.admission_time} hrs"),
                ("Address", p.address_masked, "Discharge Date", _d(s.discharge_date)),
                ("Mobile", p.mobile_masked, "Discharge Time", f"{s.discharge_time} hrs"),
                ("Ward / Bed", f"{s.ward} \u00b7 {s.bed}", "Length of Stay", f"{los} day{'s' if los != 1 else ''}"),
                ("Consultant", f"{c.name} ({c.department})", "Admitted Via", s.admitted_via),
            ],
            st, [23 * mm, 70 * mm, 27 * mm, CONTENT_W - 120 * mm],
            full_rows=[("Payer", f"Self \u2014 reimbursement claim to {s.insurer} \u00b7 Policy No. {s.policy_number} \u00b7 Member ID {s.member_id}")],
            bold_values={"Patient Name", "IP No.", "Bill No."},
        ))
        out.append(Spacer(1, 4 * mm))

        head = [Paragraph("S.No", st["head_c"]), Paragraph("Particulars", st["head"]), Paragraph("SAC / HSN", st["head_c"]),
                Paragraph("Qty", st["head_c"]), Paragraph(_x(f"Rate ({rupee})"), st["head_r"]), Paragraph(_x(f"Amount ({rupee})"), st["head_r"])]
        rows = [head]
        for i, line in enumerate(spec.lines, 1):
            rows.append([
                Paragraph(str(i), st["cell_c"]), Paragraph(_x(line.description), st["cell"]), Paragraph(_x(line.code), st["cell_c"]),
                Paragraph(str(line.qty), st["cell_c"]), Paragraph(inr(line.rate), st["cell_r"]), Paragraph(inr(line.amount), st["cell_r"]),
            ])
        items = Table(rows, colWidths=[11 * mm, 84 * mm, 21 * mm, 13 * mm, 25 * mm, CONTENT_W - 154 * mm], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), primary),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.6, RULE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, RULE),
        ]
        style += [("BACKGROUND", (0, r), (-1, r), ZEBRA) for r in range(2, len(rows), 2)]
        items.setStyle(TableStyle(style))
        out.append(items)
        out.append(Spacer(1, 3 * mm))

        totals_rows = [
            ("Gross Amount", f"{rupee} {inr(spec.total)}", False),
            ("Less: Discount", inr(0), False),
            ("Net Amount Payable", f"{rupee} {inr(spec.total)}", True),
            ("Amount Received", f"{rupee} {inr(sum(x.amount for x in spec.payments))}", False),
            ("Balance Due", inr(spec.total - sum(x.amount for x in spec.payments)), False),
        ]
        totals = Table(
            [[Paragraph(_x(label), st["total_lb" if strong else "total_l"]), Paragraph(_x(value), st["total_rb" if strong else "total_r"])]
             for label, value, strong in totals_rows],
            colWidths=[40 * mm, 32 * mm],
        )
        totals.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, RULE),
            ("LINEABOVE", (0, 2), (-1, 2), 0.8, primary), ("LINEBELOW", (0, 2), (-1, 2), 0.8, primary),
            ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#EEF4F5")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        words = [
            Paragraph(_x("Amount in words"), st["label"]),
            Paragraph(_x(rupees_in_words(spec.total)), st["value_b"]),
            Spacer(1, 2.4 * mm),
            Paragraph(_x("GST"), st["label"]),
            Paragraph(_x("Health care services by a clinical establishment are exempt from GST (Notification No. 12/2017-Central Tax (Rate), "
                         "Sl. No. 74). No GST has been charged on this bill."), st["small"]),
        ]
        summary = Table([[words, totals]], colWidths=[CONTENT_W - 76 * mm, 76 * mm])
        summary.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 8 * mm), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        out.append(summary)
        out.append(Spacer(1, 4.5 * mm))

        out.append(_section("Payment details", st, primary))
        out.append(Spacer(1, 1.5 * mm))
        pay_rows = [[Paragraph(x, st["thead"]) for x in ("Receipt No.", "Date", "Mode", "Reference")] + [Paragraph(_x(f"Amount ({rupee})"), ParagraphStyle("tr", parent=st["thead"], alignment=TA_RIGHT))]]
        for pay in spec.payments:
            pay_rows.append([Paragraph(_x(pay.receipt_no), st["cell"]), Paragraph(_d(s.discharge_date), st["cell"]),
                             Paragraph(_x(pay.mode), st["cell"]), Paragraph(_x(pay.reference), st["cell"]), Paragraph(inr(pay.amount), st["cell_r"])])
        pay = Table(pay_rows, colWidths=[42 * mm, 23 * mm, 27 * mm, CONTENT_W - 120 * mm, 28 * mm])
        pay.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4F5")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 2.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        out.append(pay)
        out.append(Spacer(1, 4 * mm))

        notes = [
            "This is a computer-generated bill. E. &amp; O.E.",
            "Please retain the original bill, discharge summary and investigation reports for your insurance reimbursement claim.",
            f"For billing queries write to {_x(h.email)} or call {_x(h.phone)} (Billing, Ext. 2140).",
        ]
        out.append(Paragraph("<b>Notes</b>", st["note"]))
        for i, note in enumerate(notes, 1):
            out.append(Paragraph(f"{i}. {note}", st["note"]))
        out.append(Spacer(1, 5 * mm))

        qr = _qr(f"https://{h.website.removeprefix('www.')}/verify?bill={spec.bill_no.replace('/', '-')}&amt={spec.total:.2f}", 19 * mm)
        stamp = (h.name.upper(), "PAID", f"{_d(s.discharge_date)}  \u00b7  CASH COUNTER")
        # Columns: QR | gap | prepared | gap | checked | gap | authorised signatory (stamp + signature).
        gap, qr_w, col_w = 5 * mm, 26 * mm, 38 * mm
        sig_w = CONTENT_W - qr_w - 2 * col_w - 3 * gap
        sign_rows = [
            [qr, "", "", "", "", "", _Signature(sig_w, 15 * mm, seed=spec.bill_no, stamp=stamp)],
            [Paragraph(_x("Scan to verify"), ParagraphStyle("q", parent=st["note"], alignment=TA_LEFT)), "",
             [Paragraph(_x(spec.prepared_by), st["sig_b"]), Paragraph(_x("Prepared by (Billing)"), st["sig"])], "",
             [Paragraph(_x(spec.checked_by), st["sig_b"]), Paragraph(_x("Checked by (Accounts)"), st["sig"])], "",
             [Paragraph(_x(f"For {h.name}"), st["sig_b"]), Paragraph(_x("Authorised Signatory"), st["sig"])]],
        ]
        sign = Table(sign_rows, colWidths=[qr_w, gap, col_w, gap, col_w, gap, sig_w], rowHeights=[16 * mm, None])
        sign.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, 0), "BOTTOM"), ("VALIGN", (0, 1), (-1, 1), "TOP"),
            ("LINEABOVE", (2, 1), (2, 1), 0.5, MUTED), ("LINEABOVE", (4, 1), (4, 1), 0.5, MUTED), ("LINEABOVE", (6, 1), (6, 1), 0.5, MUTED),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 0), ("TOPPADDING", (0, 1), (-1, 1), 2),
        ]))
        out.append(KeepTogether([sign]))
        return out

    _build(
        path, story, hospital=h, running_title="In-patient Final Bill (continued)",
        running_right=(f"{p.display_name} \u00b7 {p.age} Y / {p.sex}", f"UHID {p.uhid} \u00b7 IP No. {s.ip_no} \u00b7 Bill No. {spec.bill_no}"),
        footer_left=f"Bill No. {spec.bill_no}  \u00b7  Printed on {_d(s.discharge_date)} {spec.bill_time} by {spec.printed_by}",
        meta_title=f"In-patient Final Bill - {p.name}", meta_subject=f"IP No. {s.ip_no}",
    )
    return path


def render_discharge_summary(path: Path | str, spec: DischargeSummarySpec) -> Path:
    path = Path(path)
    h, p, s = spec.hospital, spec.patient, spec.stay
    doc = s.consultant
    primary = colors.HexColor(h.primary)
    st = _styles(primary)

    def section(title: str, *flowables) -> list:
        """A heading never ends a page (CondPageBreak); the body may flow on."""
        return [Spacer(1, 3 * mm), CondPageBreak(22 * mm), _section(title, st, primary), Spacer(1, 1.4 * mm), *flowables]

    def bullets(items: list[str]) -> list[Paragraph]:
        return [Paragraph(_x(item), st["bullet"], bulletText="\u2022") for item in items]

    def para(text: str) -> Paragraph:
        return Paragraph(_x(text), st["base"])

    def story():
        out = []
        left = [
            Paragraph(f"<b>{_x(f'Department of {doc.department}')}</b>", ParagraphStyle("dep", parent=st["small"], textColor=primary)),
            Paragraph(_x(f"Consultant: {doc.name}"), st["muted"]),
        ]
        out.append(_title_row(left, "DISCHARGE SUMMARY", _barcode(p.uhid, f"UHID {p.uhid}", st), primary))
        out.append(Spacer(1, 3.2 * mm))
        out.append(_kv_block(
            [
                ("Patient Name", p.display_name, "IP No.", s.ip_no),
                ("Age / Sex", f"{p.age} Y / {p.sex}", "UHID", p.uhid),
                ("Admission Date", _d(s.admission_date), "Admission Time", f"{s.admission_time} hrs"),
                ("Discharge Date", _d(s.discharge_date), "Discharge Time", f"{s.discharge_time} hrs"),
                ("Ward / Bed", f"{s.ward} \u00b7 {s.bed}", "Admitted Via", s.admitted_via),
                ("Consultant", doc.name, "Department", doc.department),
            ],
            st, [25 * mm, 72 * mm, 27 * mm, CONTENT_W - 124 * mm],
            full_rows=[("Discharge Type", spec.discharge_type)],
            bold_values={"Patient Name", "IP No."},
        ))

        diag = Table([[
            [Paragraph(_x("FINAL DIAGNOSIS"), ParagraphStyle("dl", parent=st["section"], fontSize=7.6)),
             Spacer(1, 1), Paragraph(_x(spec.final_diagnosis), st["diag"])],
            [Paragraph(_x("ICD-10"), ParagraphStyle("il", parent=st["section"], fontSize=7.6, alignment=TA_RIGHT)),
             Spacer(1, 1), Paragraph(_x(spec.icd10), ParagraphStyle("ic", parent=st["diag"], alignment=TA_RIGHT))],
        ]], colWidths=[CONTENT_W - 30 * mm, 30 * mm])
        diag.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF4F5")),
            ("LINEBEFORE", (0, 0), (0, 0), 2.2, primary),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        out.append(Spacer(1, 3.4 * mm))
        out.append(diag)

        out.extend(section("Presenting complaints", *bullets(spec.presenting_complaints)))
        out.extend(section("History of present illness", para(spec.history_of_present_illness)))
        out.extend(section(
            "Past, personal & allergy history",
            Paragraph(f"<b>Past history:</b> {_x(spec.past_history)}", st["base"]),
            Paragraph(f"<b>Personal history:</b> {_x(spec.personal_history)}", st["base"]),
            Paragraph(f"<b>Drug allergies:</b> {_x(spec.allergies)}", st["base"]),
        ))

        vitals = Table(
            [[Paragraph(_x(k).replace("SpO2", "SpO<sub>2</sub>"), st["thead_c"]) for k, _ in spec.admission_vitals],
             [Paragraph(_x(v), st["cell_c"]) for _, v in spec.admission_vitals]],
            colWidths=[CONTENT_W / len(spec.admission_vitals)] * len(spec.admission_vitals),
        )
        vitals.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, RULE), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4F5")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ]))
        systemic = [Paragraph(f"<b>{_x(system)}:</b> {_x(finding)}", st["base"]) for system, finding in spec.systemic_examination]
        out.extend(section("Examination on admission", vitals, Spacer(1, 2 * mm),
                           Paragraph(f"<b>General:</b> {_x(spec.general_examination)}", st["base"]), *systemic))

        n = len(spec.lab_days)
        day_w = min(26 * mm, (CONTENT_W - 44 * mm - 34 * mm) / n)
        param_w = CONTENT_W - 34 * mm - n * day_w
        head = [Paragraph("Parameter", st["thead"])]
        for offset in spec.lab_days:
            d = s.admission_date + timedelta(days=offset)
            head.append(Paragraph(f"{d.strftime('%d-%m')}<br/><font size='6.6' color='#5B6670'>Day {offset + 1}</font>", st["thead_c"]))
        head.append(Paragraph("Ref. range", st["thead_c"]))
        lab = [head] + [
            [Paragraph(_x(row.parameter), st["cell"])] + [Paragraph(_x(v or "\u2014"), st["cell_c"]) for v in row.values]
            + [Paragraph(_x(row.reference), ParagraphStyle("ref", parent=st["cell_c"], textColor=MUTED, fontSize=7.4))]
            for row in spec.lab_rows
        ]
        lab_t = Table(lab, colWidths=[param_w] + [day_w] * n + [34 * mm], repeatRows=1)
        lab_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4F5")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE), ("BOX", (0, 0), (-1, -1), 0.5, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.1),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (0, -1), 5),
        ]))
        other = Table(
            [[Paragraph(_x(k), ParagraphStyle("ok", parent=st["cell"], fontName=_fonts().bold)), Paragraph(_x(v), st["cell"])]
             for k, v in spec.other_investigations],
            colWidths=[62 * mm, CONTENT_W - 62 * mm],
        )
        other.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.7), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        out.extend(section("Key investigations", lab_t))
        out.append(Spacer(1, 2.4 * mm))
        out.append(other)

        out.extend(section("Course in hospital", para(spec.course_in_hospital)))
        out.extend(section("Treatment given", *bullets(spec.treatment_given),
                           Paragraph(f"<b>Procedures:</b> {_x(spec.procedures)}", st["base"])))
        out.extend(section("Condition at discharge", Paragraph(f"<b>{_x(spec.condition_at_discharge)}</b>", st["base"]),
                           Paragraph(f"<b>Vitals at discharge:</b> {_x(spec.discharge_vitals)}", st["base"])))

        med_head = [Paragraph(x, st["thead"]) for x in ("#", "Medicine", "Dose", "Route", "Frequency / timing", "Duration")]
        med_rows = [med_head] + [
            [Paragraph(str(i), st["cell"]), Paragraph(f"<b>{_x(m.medicine)}</b>", st["cell"]), Paragraph(_x(m.dose), st["cell"]),
             Paragraph(_x(m.route), st["cell"]), Paragraph(_x(m.frequency), st["cell"]), Paragraph(_x(m.duration), st["cell"])]
            for i, m in enumerate(spec.medications, 1)
        ]
        meds = Table(med_rows, colWidths=[8 * mm, 54 * mm, 30 * mm, 14 * mm, CONTENT_W - 124 * mm, 18 * mm], repeatRows=1)
        meds.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4F5")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE), ("BOX", (0, 0), (-1, -1), 0.5, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.1),
        ]))
        out.extend(section("Discharge medications", meds))
        out.extend(section("Advice on discharge", *bullets(spec.advice),
                           Spacer(1, 1.2 * mm),
                           Paragraph(f"<b>Return to the Emergency Department immediately if:</b> {_x(spec.warning_signs)}", st["base"])))
        out.extend(section("Follow-up", para(f"{spec.follow_up} 24x7 Emergency: {h.emergency_phone}.")))

        if spec.hidden_injection:
            out.append(Spacer(1, 2 * mm))
            out.append(_HiddenText(spec.hidden_injection))

        # Columns: prepared by | gap | patient / relative | gap | consultant (stamp + signature).
        gap, col_w, sig_w = 6 * mm, 50 * mm, 70 * mm
        doc_stamp = (doc.name.upper(), doc.qualifications, f"Regn. No. {doc.registration_no}")
        sign = Table(
            [
                ["", "", "", "", _Signature(sig_w, 15 * mm, seed=doc.name, stamp=doc_stamp, stamp_kind="doctor")],
                [
                    [Paragraph(_x(spec.prepared_by), st["sig_b"]), Paragraph(_x("Prepared by"), st["sig"])], "",
                    [Paragraph(_x("Patient / relative"), st["sig_b"]), Paragraph(_x("Summary explained and received"), st["sig"])], "",
                    [Paragraph(_x(doc.name), st["sig_b"]),
                     Paragraph(_x(doc.qualifications), st["sig"]),
                     Paragraph(_x(f"{doc.designation} · Regn. No. {doc.registration_no}"), st["sig"])],
                ],
            ],
            colWidths=[col_w, gap, CONTENT_W - 2 * gap - col_w - sig_w, gap, sig_w], rowHeights=[15 * mm, None],
        )
        sign.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, 0), "BOTTOM"), ("VALIGN", (0, 1), (-1, 1), "TOP"),
            ("LINEABOVE", (0, 1), (0, 1), 0.5, MUTED), ("LINEABOVE", (2, 1), (2, 1), 0.5, MUTED), ("LINEABOVE", (4, 1), (4, 1), 0.5, MUTED),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 0), ("TOPPADDING", (0, 1), (-1, 1), 2),
        ]))
        out.append(KeepTogether([Spacer(1, 4 * mm), sign]))
        return out

    _build(
        path, story, hospital=h, running_title="Discharge Summary (continued)",
        running_right=(f"{p.display_name} \u00b7 {p.age} Y / {p.sex}", f"UHID {p.uhid} \u00b7 IP No. {s.ip_no}"),
        footer_left=f"Discharge Summary  \u00b7  UHID {p.uhid}  \u00b7  IP No. {s.ip_no}  \u00b7  Printed on {_d(s.discharge_date)} {s.discharge_time}",
        meta_title=f"Discharge Summary - {p.name}", meta_subject=f"IP No. {s.ip_no}",
    )
    return path
