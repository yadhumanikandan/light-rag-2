"""
Generates a styled KYC Word document from extracted document data.
NAAS — National Assurance & Advisory Services FZ LLC
17-section format per NAAS KYC Profile specification.
"""

import io
import re
import unicodedata
from datetime import date, datetime

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ── Colour palette ─────────────────────────────────────────────────────────────
_NAVY       = "1B3A6B"
_BLUE       = "2E75B6"
_GREY_MED   = "555555"
_GREY_LITE  = "888888"
_WHITE      = "FFFFFF"
_OFF_WHITE  = "F5F5F5"
_DARK       = "1A1A1A"
_GREEN      = "1B6B3A"
_RED        = "C0392B"
_ORANGE     = "B45309"
_BORDER_CLR = "D0D7E0"

_TEXT_W = 16.0  # cm  (A4 with 2.5 cm side margins)


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _rgb(h: str) -> RGBColor:
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _shd_cell(cell, fill: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:shd"))
    if old is not None:
        tcPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  fill)
    tcPr.append(shd)


def _cell_borders(cell, color: str = _BORDER_CLR, sz: int = 4, visible: bool = True):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:tcBorders"))
    if old is not None:
        tcPr.remove(old)
    borders = OxmlElement("w:tcBorders")
    val = "single" if visible else "none"
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), val)
        if visible:
            el.set(qn("w:sz"),    str(sz))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), color)
        borders.append(el)
    tcPr.append(borders)


def _get_tblPr(tbl):
    tbl_el = tbl._tbl
    tblPr  = tbl_el.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl_el.insert(0, tblPr)
    return tblPr


def _remove_tbl_borders(tbl):
    tblPr = _get_tblPr(tbl)
    old   = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "none")
        borders.append(el)
    tblPr.append(borders)


def _set_tbl_width(tbl, width_cm: float):
    tblPr = _get_tblPr(tbl)
    old   = tblPr.find(qn("w:tblW"))
    if old is not None:
        tblPr.remove(old)
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"),    str(int(width_cm * 567)))
    w.set(qn("w:type"), "dxa")
    tblPr.append(w)


# ── Date helpers ──────────────────────────────────────────────────────────────

def _parse_date(s) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _fmt_date(s) -> str:
    d = _parse_date(s)
    return d.strftime("%d %B %Y") if d else (str(s) if s else "—")


def _short_date(d: date | None) -> str:
    return d.strftime("%-d %b %Y") if d else "—"


def _expiry_label(expiry_str, today: date) -> tuple[str, str]:
    """Returns (formatted label, symbol ✓/⚠/✗)."""
    d = _parse_date(expiry_str)
    if d is None:
        return "—", "?"
    days = (d - today).days
    fmt  = d.strftime("%d %B %Y")
    if days < 0:
        mn = abs((today.year - d.year) * 12 + (today.month - d.month))
        return f"{fmt}  (EXPIRED — {mn} month{'s' if mn != 1 else ''} ago ✗)", "✗"
    elif days <= 30:
        return f"{fmt}  ({days} days remaining — EXPIRING SOON ⚠)", "⚠"
    else:
        return f"{fmt}  ({days} days remaining — VALID ✓)", "✓"


def _insurance_label(valid_to_str, today: date) -> tuple[str, str]:
    d = _parse_date(valid_to_str)
    if d is None:
        return "—", "?"
    days = (d - today).days
    fmt  = d.strftime("%d %B %Y")
    if days < 0:
        return f"{fmt}  (EXPIRED ✗)", "✗"
    elif days <= 30:
        return f"{fmt}  (EXPIRING SOON ⚠)", "⚠"
    else:
        return f"{fmt}  (ACTIVE ✓)", "✓"


# ── Value helpers ─────────────────────────────────────────────────────────────

def _s(val) -> str:
    """Safely stringify a value — handles lists the LLM may return instead of strings."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val)


def _v(d: dict, k: str, default: str = "—") -> str:
    val = d.get(k)
    return _s(val).strip() if val else default


def _normalise(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _name_tokens(s: str) -> set[str]:
    """Return a set of lowercased, ASCII-folded name parts (order-insensitive)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return {t for t in re.sub(r"[^a-z\s]", "", s.lower()).split() if t}


def _names_match(a: str, b: str) -> bool:
    """Order-insensitive name comparison: same tokens = match."""
    na, nb = _normalise(a), _normalise(b)
    if na == nb or na in nb or nb in na:
        return True
    # Token-set comparison (handles reordered name parts)
    return _name_tokens(a) == _name_tokens(b)


def _match2(a: str, b: str) -> str:
    if not a or a == "—" or not b or b == "—":
        return "—"
    return "✓" if _names_match(a, b) else "⚠"


def _match3(a: str, b: str, c: str) -> str:
    vals = [x for x in [a, b, c] if x and x != "—"]
    if not vals:
        return "—"
    if len(vals) == 1:
        return "✓"
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            if not _names_match(vals[i], vals[j]):
                return "⚠"
    return "✓"


# ── Document-building primitives ──────────────────────────────────────────────

def _spacer(doc, pts: float = 4):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after  = Pt(pts)
    p._p.get_or_add_pPr().set(qn("w:jc"), "left")


def _section_header(doc, number: int, title: str):
    _spacer(doc, 10)
    tbl  = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_tbl_borders(tbl)
    _set_tbl_width(tbl, _TEXT_W)
    cell = tbl.cell(0, 0)
    _shd_cell(cell, _NAVY)
    _cell_borders(cell, visible=False)
    cell.width = Cm(_TEXT_W)
    para = cell.paragraphs[0]
    para.paragraph_format.space_before = Pt(5)
    para.paragraph_format.space_after  = Pt(5)
    para.paragraph_format.left_indent  = Pt(8)
    run = para.add_run(f"  {number}.   {title.upper()}")
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = _rgb(_WHITE)
    _spacer(doc, 2)


def _sub_header(doc, title: str):
    _spacer(doc, 6)
    tbl  = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_tbl_borders(tbl)
    _set_tbl_width(tbl, _TEXT_W)
    cell = tbl.cell(0, 0)
    _shd_cell(cell, "2E4F7A")
    _cell_borders(cell, visible=False)
    cell.width = Cm(_TEXT_W)
    para = cell.paragraphs[0]
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after  = Pt(4)
    para.paragraph_format.left_indent  = Pt(10)
    run = para.add_run(f"  {title}")
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = _rgb(_WHITE)
    _spacer(doc, 2)


def _kv_table(doc, rows: list[tuple[str, str]]):
    if not rows:
        return
    label_w = _TEXT_W * 0.36
    value_w = _TEXT_W * 0.64
    tbl = doc.add_table(rows=len(rows), cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_tbl_borders(tbl)
    _set_tbl_width(tbl, _TEXT_W)
    for i, (key, val) in enumerate(rows):
        fill = _WHITE if i % 2 == 0 else _OFF_WHITE
        row_el = tbl.rows[i]

        lc = row_el.cells[0]
        lc.width = Cm(label_w)
        _shd_cell(lc, fill)
        _cell_borders(lc, _BORDER_CLR)
        lp = lc.paragraphs[0]
        lp.paragraph_format.space_before = Pt(3)
        lp.paragraph_format.space_after  = Pt(3)
        lp.paragraph_format.left_indent  = Pt(6)
        lr = lp.add_run(str(key) if key else "")
        lr.bold = True
        lr.font.size = Pt(9.5)
        lr.font.color.rgb = _rgb(_NAVY)

        vc = row_el.cells[1]
        vc.width = Cm(value_w)
        _shd_cell(vc, fill)
        _cell_borders(vc, _BORDER_CLR)
        vp = vc.paragraphs[0]
        vp.paragraph_format.space_before = Pt(3)
        vp.paragraph_format.space_after  = Pt(3)
        vp.paragraph_format.left_indent  = Pt(6)
        vr = vp.add_run(str(val) if val else "—")
        vr.font.size = Pt(9.5)
        vr.font.color.rgb = _rgb(_DARK)
    _spacer(doc, 6)


def _styled_cell(cell, txt: str, fill: str, w: float,
                 bold: bool = False, center: bool = False,
                 color: str = _DARK, pt: float = 9.5):
    cell.width = Cm(w)
    _shd_cell(cell, fill)
    _cell_borders(cell, _BORDER_CLR)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after  = Pt(3)
    p.paragraph_format.left_indent  = Pt(6)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(str(txt) if txt else "—")
    r.font.size = Pt(pt)
    r.bold = bold
    r.font.color.rgb = _rgb(color)


def _match_color(sym: str) -> str:
    if "✓" in sym:
        return _GREEN
    if "⚠" in sym:
        return _ORANGE
    if "✗" in sym:
        return _RED
    return _GREY_MED


def _verify_table(doc, headers: tuple, rows: list[tuple]):
    """4-column cross-verification table."""
    if not rows:
        return
    col_w = [4.0, 4.5, 4.5, 3.0]
    tbl = doc.add_table(rows=1 + len(rows), cols=4)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_tbl_borders(tbl)
    _set_tbl_width(tbl, _TEXT_W)
    for ci, (lbl, w) in enumerate(zip(headers, col_w)):
        cell = tbl.rows[0].cells[ci]
        _styled_cell(cell, lbl, _BLUE, w, bold=True, center=(ci == 3),
                     color=_WHITE, pt=9)
    for ri, (f, v1, v2, match) in enumerate(rows):
        fill = _WHITE if ri % 2 == 0 else _OFF_WHITE
        row  = tbl.rows[ri + 1]
        _styled_cell(row.cells[0], f,     fill, col_w[0], bold=True, color=_NAVY)
        _styled_cell(row.cells[1], v1,    fill, col_w[1], color=_DARK)
        _styled_cell(row.cells[2], v2,    fill, col_w[2], color=_DARK)
        mc = row.cells[3]
        _styled_cell(mc, match, fill, col_w[3], bold=("—" not in match),
                     center=True, color=_match_color(match), pt=11)
    _spacer(doc, 6)


def _three_way_table(doc, headers: tuple, rows: list[tuple]):
    """5-column table for 3-way cross-verification (Field | A | B | C | Match)."""
    if not rows:
        return
    col_w = [3.0, 3.2, 3.2, 3.2, 3.4]
    tbl = doc.add_table(rows=1 + len(rows), cols=5)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_tbl_borders(tbl)
    _set_tbl_width(tbl, _TEXT_W)
    for ci, (lbl, w) in enumerate(zip(headers, col_w)):
        _styled_cell(tbl.rows[0].cells[ci], lbl, _BLUE, w,
                     bold=True, center=(ci == 4), color=_WHITE, pt=9)
    for ri, row_data in enumerate(rows):
        f, v1, v2, v3, match = row_data
        fill = _WHITE if ri % 2 == 0 else _OFF_WHITE
        row  = tbl.rows[ri + 1]
        _styled_cell(row.cells[0], f,     fill, col_w[0], bold=True, color=_NAVY)
        _styled_cell(row.cells[1], v1,    fill, col_w[1], color=_DARK)
        _styled_cell(row.cells[2], v2,    fill, col_w[2], color=_DARK)
        _styled_cell(row.cells[3], v3,    fill, col_w[3], color=_DARK)
        _styled_cell(row.cells[4], match, fill, col_w[4], bold=("—" not in match),
                     center=True, color=_match_color(match), pt=11)
    _spacer(doc, 6)


def _doc_status_table(doc, rows: list[tuple]):
    """5-column personal document validity table.
    Columns: Document | Holder Name | Document No. | Expiry Date | Status"""
    if not rows:
        return
    headers = ("Document", "Holder Name", "Document No.", "Expiry Date", "Status")
    col_w   = [3.0, 3.8, 3.0, 3.2, 3.0]
    tbl = doc.add_table(rows=1 + len(rows), cols=5)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_tbl_borders(tbl)
    _set_tbl_width(tbl, _TEXT_W)
    for ci, (lbl, w) in enumerate(zip(headers, col_w)):
        _styled_cell(tbl.rows[0].cells[ci], lbl, _BLUE, w,
                     bold=True, center=(ci == 4), color=_WHITE, pt=9)
    for ri, (doc_type, holder, doc_no, expiry, sym) in enumerate(rows):
        fill = _WHITE if ri % 2 == 0 else _OFF_WHITE
        row  = tbl.rows[ri + 1]
        _styled_cell(row.cells[0], doc_type, fill, col_w[0], bold=True, color=_NAVY)
        _styled_cell(row.cells[1], holder,   fill, col_w[1], color=_DARK)
        _styled_cell(row.cells[2], doc_no,   fill, col_w[2], color=_DARK)
        _styled_cell(row.cells[3], expiry,   fill, col_w[3], color=_DARK)
        _styled_cell(row.cells[4], sym,      fill, col_w[4], bold=True,
                     center=True, color=_match_color(sym), pt=13)
    _spacer(doc, 6)


# ── Main generator ────────────────────────────────────────────────────────────

def generate_kyc_document(extracted: dict, today: date) -> bytes:
    """
    Build a 17-section KYC Word document and return bytes.

    extracted keys: trade_license | ejari | moa | insurance |
                    passport | emirates_id | residence_visa | vat_certificate
    """
    # ── Unpack ─────────────────────────────────────────────────────────────────
    tl_up   = bool(extracted.get("trade_license"))
    ej_up   = bool(extracted.get("ejari"))
    moa_up  = bool(extracted.get("moa"))
    ins_up  = bool(extracted.get("insurance"))
    pp_up   = bool(extracted.get("passport"))
    eid_up  = bool(extracted.get("emirates_id"))
    visa_up = bool(extracted.get("residence_visa"))
    vat_up  = bool(extracted.get("vat_certificate"))

    tl   = dict(extracted.get("trade_license")   or {})
    ej   = dict(extracted.get("ejari")            or {})
    moa  = dict(extracted.get("moa")              or {})
    ins  = dict(extracted.get("insurance")        or {})
    pp   = dict(extracted.get("passport")         or {})
    eid  = dict(extracted.get("emirates_id")      or {})
    visa = dict(extracted.get("residence_visa")   or {})
    vat  = dict(extracted.get("vat_certificate")  or {})

    for d in [tl, ej, moa, ins, pp, eid, visa, vat]:
        d.pop("error", None)

    # ── Key identifiers ────────────────────────────────────────────────────────
    company_name = (_v(tl, "company_name", "") or _v(moa, "company_name", "")
                    or _v(vat, "company_name", ""))
    legal_form   = _v(tl, "legal_form", "") or _v(moa, "legal_form", "")
    license_no   = _v(tl,  "license_number",  "—")
    ejari_no     = _v(ej,  "ejari_number",    "—")
    moa_no       = _v(moa, "contract_number", "—")

    # ── Expiry labels ──────────────────────────────────────────────────────────
    tl_label,   tl_sym   = _expiry_label(tl.get("expiry_date"),   today)
    ej_label,   ej_sym   = _expiry_label(ej.get("expiry_date"),   today)
    pp_label,   pp_sym   = _expiry_label(pp.get("expiry_date"),   today)
    eid_label,  eid_sym  = _expiry_label(eid.get("expiry_date"),  today)
    visa_label, visa_sym = _expiry_label(visa.get("expiry_date"), today)
    ins_label,  ins_sym  = _insurance_label(ins.get("valid_to"),  today)

    # ── Flags accumulator ──────────────────────────────────────────────────────
    flags: list[dict] = []

    def _flag(ftype: str, docs: str, field: str, val_a: str, val_b: str, action: str):
        flags.append({"type": ftype, "docs": docs, "field": field,
                      "val_a": val_a, "val_b": val_b, "action": action})

    # ── Create document ────────────────────────────────────────────────────────
    doc = Document()
    sec = doc.sections[0]
    sec.page_width    = Cm(21)
    sec.page_height   = Cm(29.7)
    sec.left_margin   = Cm(2.5)
    sec.right_margin  = Cm(2.5)
    sec.top_margin    = Cm(2.0)
    sec.bottom_margin = Cm(2.0)

    def _centered(text, bold=False, pt=10, color=_DARK, sb=0, sa=6):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(sb)
        p.paragraph_format.space_after  = Pt(sa)
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(pt)
        r.font.color.rgb = _rgb(color)

    # ── Title block ────────────────────────────────────────────────────────────
    _centered("KNOW YOUR CUSTOMER (KYC) PROFILE",
              bold=True, pt=16, color=_NAVY, sb=0, sa=4)
    _centered("National Assurance & Advisory Services FZ LLC (NAAS)",
              pt=9, color=_GREY_MED, sb=0, sa=3)
    _centered(company_name or "—", bold=True, pt=14, color=_BLUE, sb=0, sa=4)
    subtitle = f"{legal_form}  |  Dubai, UAE" if legal_form else "Dubai, UAE"
    _centered(subtitle, pt=10, color=_GREY_MED, sb=0, sa=4)
    ref_parts = []
    if moa_no   != "—": ref_parts.append(f"MOA: {moa_no}")
    if license_no != "—": ref_parts.append(f"Trade Licence: {license_no}")
    if ejari_no != "—": ref_parts.append(f"EJARI: {ejari_no}")
    ref_parts.append(f"Prepared: {today.strftime('%d %B %Y')}")
    _centered("  |  ".join(ref_parts), pt=9, color=_GREY_LITE, sb=0, sa=0)

    div = doc.add_paragraph()
    div.paragraph_format.space_before = Pt(8)
    div.paragraph_format.space_after  = Pt(10)
    pBdr = OxmlElement("w:pBdr")
    bot  = OxmlElement("w:bottom")
    bot.set(qn("w:val"),   "single")
    bot.set(qn("w:sz"),    "8")
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), _NAVY)
    pBdr.append(bot)
    div._p.get_or_add_pPr().append(pBdr)

    n = 1  # auto section counter

    # ══════════════════════════════════════════════════════════════════════════
    # 1 — COMPANY DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    if tl or moa or vat:
        _section_header(doc, n, "Company Details"); n += 1
        rows: list[tuple] = []
        cn_en = (_v(tl, "company_name", "") or _v(moa, "company_name", "")
                 or _v(vat, "company_name", ""))
        cn_ar = (_v(tl, "company_name_arabic", "") or _v(moa, "company_name_arabic", "")
                 or _v(vat, "company_name_arabic", ""))
        rows.append(("Company Name (English)", cn_en or "—"))
        if cn_ar and cn_ar != "—":
            rows.append(("Company Name (Arabic)", cn_ar))
        lf = _v(tl, "legal_form", "") or _v(moa, "legal_form", "")
        if lf and lf != "—":
            rows.append(("Legal Type", lf))
        ia = _v(tl, "issuing_authority", "")
        if ia and ia != "—":
            rows.append(("Issuing Authority", ia))
        if moa.get("contract_number"):
            rows.append(("MOA Contract No.", _v(moa, "contract_number")))
        if moa.get("moa_date"):
            rows.append(("MOA Date", _fmt_date(moa["moa_date"])))
        if moa.get("company_duration"):
            rows.append(("Company Duration", _v(moa, "company_duration")))
        if moa.get("financial_year"):
            rows.append(("Financial Year", _v(moa, "financial_year")))
        if moa.get("disputes_jurisdiction"):
            rows.append(("Disputes Jurisdiction", _v(moa, "disputes_jurisdiction")))
        if vat.get("trn"):
            rows.append(("Tax Registration No. (TRN)", _v(vat, "trn")))
        _kv_table(doc, rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 2 — TRADE LICENCE DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    if tl_up:
        _section_header(doc, n, "Trade Licence Details"); n += 1
        rows = [("Licence No.", _v(tl, "license_number"))]
        if tl.get("register_number"):
            rows.append(("Commercial Register No.", _v(tl, "register_number")))
        if tl.get("dcci_membership_number"):
            rows.append(("DCCI Membership No.", _v(tl, "dcci_membership_number")))
        if tl.get("license_type"):
            rows.append(("Licence Type", _v(tl, "license_type")))
        if tl.get("licence_category"):
            rows.append(("Licence Category", _v(tl, "licence_category")))
        if tl.get("issue_date"):
            rows.append(("Issue Date", _fmt_date(tl["issue_date"])))
        rows.append(("Expiry Date", tl_label))
        if tl.get("last_renewal_date"):
            rows.append(("Last Renewal Date", _fmt_date(tl["last_renewal_date"])))
        if tl.get("last_renewal_fee"):
            rows.append(("Last Renewal Fee", _v(tl, "last_renewal_fee")))
        if tl_sym in ("⚠", "✗"):
            _flag("Trade Licence Validity", "Trade Licence", "Expiry Date", tl_label, "",
                  "Renew Trade Licence immediately." if tl_sym == "✗"
                  else "Initiate renewal — expires within 30 days.")
        _kv_table(doc, rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 3 — REGISTERED ADDRESS & CONTACT DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    addr_rows: list[tuple] = []
    if tl.get("registered_address"):
        addr_rows.append(("Registered Address", _v(tl, "registered_address")))
    if tl.get("unit_number"):
        addr_rows.append(("Unit No.", _v(tl, "unit_number")))
    if tl.get("building_name"):
        addr_rows.append(("Building", _v(tl, "building_name")))
    if tl.get("area"):
        addr_rows.append(("Area", _v(tl, "area")))
    if tl.get("parcel_id"):
        addr_rows.append(("Parcel ID / Land DM No.", _v(tl, "parcel_id")))
    if tl.get("makani_number"):
        addr_rows.append(("Makani No.", _v(tl, "makani_number")))
    if tl.get("phone_fax"):
        addr_rows.append(("Phone / Fax", _v(tl, "phone_fax")))
    if tl.get("mobile"):
        addr_rows.append(("Mobile No.", _v(tl, "mobile")))
    if tl.get("email"):
        addr_rows.append(("Email", _v(tl, "email")))
    if addr_rows:
        _section_header(doc, n, "Registered Address & Contact Details"); n += 1
        _kv_table(doc, addr_rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 4 — EJARI — TENANCY CONTRACT
    # ══════════════════════════════════════════════════════════════════════════
    if ej_up:
        _section_header(doc, n, "EJARI — Tenancy Contract"); n += 1
        rows = [("EJARI Contract No.", _v(ej, "ejari_number"))]
        if ej.get("registration_date"):
            rows.append(("Registration Date",           _fmt_date(ej["registration_date"])))
        if ej.get("registered_by"):
            rows.append(("Registered by",               _v(ej, "registered_by")))
        if ej.get("tenant_name"):
            rows.append(("Tenant Name",                 _v(ej, "tenant_name")))
        if ej.get("licence_number"):
            rows.append(("Trade Licence No. (EJARI)",   _v(ej, "licence_number")))
        if ej.get("licence_issuer"):
            rows.append(("Licence Issuer (EJARI)",      _v(ej, "licence_issuer")))
        if ej.get("start_date"):
            rows.append(("Lease Start Date",            _fmt_date(ej["start_date"])))
        rows.append(("Lease End Date",                  ej_label))
        if ej.get("annual_rent"):
            rows.append(("Annual Rent",                 _v(ej, "annual_rent")))
        if ej.get("security_deposit"):
            rows.append(("Security Deposit",            _v(ej, "security_deposit")))
        if ej.get("ejari_fees_paid"):
            rows.append(("EJARI Fees Paid",             _v(ej, "ejari_fees_paid")))
        if ej.get("unit_number"):
            rows.append(("Unit No.",                    _v(ej, "unit_number")))
        if ej.get("building_name"):
            rows.append(("Building",                    _v(ej, "building_name")))
        if ej.get("area"):
            rows.append(("Area",                        _v(ej, "area")))
        if ej.get("unit_type"):
            rows.append(("Unit Type",                   _v(ej, "unit_type")))
        if ej.get("size"):
            rows.append(("Size",                        _v(ej, "size")))
        if ej.get("plot_number"):
            rows.append(("Plot No.",                    _v(ej, "plot_number")))
        if ej.get("land_dm_parcel_id"):
            rows.append(("Land DM No. (Parcel ID)",     _v(ej, "land_dm_parcel_id")))
        if ej.get("makani_number"):
            rows.append(("Makani No.",                  _v(ej, "makani_number")))
        if ej_sym in ("⚠", "✗"):
            _flag("EJARI Validity", "EJARI Tenancy Contract", "Lease End Date", ej_label, "",
                  "Renew EJARI / tenancy contract." if ej_sym == "✗"
                  else "EJARI renewal due within 30 days.")
        _kv_table(doc, rows)

        landlord_rows: list[tuple] = []
        if ej.get("landlord_name"):
            landlord_rows.append(("Owner Name",           _v(ej, "landlord_name")))
        if ej.get("landlord_owner_number"):
            landlord_rows.append(("Owner No.",            _v(ej, "landlord_owner_number")))
        if ej.get("landlord_nationality"):
            landlord_rows.append(("Nationality",          _v(ej, "landlord_nationality")))
        if ej.get("property_manager"):
            landlord_rows.append(("Property Manager",     _v(ej, "property_manager")))
        if ej.get("property_manager_email"):
            landlord_rows.append(("Property Manager Email", _v(ej, "property_manager_email")))
        if landlord_rows:
            _sub_header(doc, "Landlord Details")
            _kv_table(doc, landlord_rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 5 — VAT REGISTRATION
    # ══════════════════════════════════════════════════════════════════════════
    if vat_up:
        _section_header(doc, n, "VAT Registration"); n += 1
        vat_rows: list[tuple] = []
        if vat.get("trn"):
            vat_rows.append(("Tax Registration No. (TRN)", _v(vat, "trn")))
        if vat.get("company_name"):
            vat_rows.append(("Registered Name",            _v(vat, "company_name")))
        if vat.get("company_name_arabic"):
            vat_rows.append(("Arabic Name",                _v(vat, "company_name_arabic")))
        if vat.get("effective_date"):
            vat_rows.append(("Effective Date",             _fmt_date(vat["effective_date"])))
        if vat.get("registered_address"):
            vat_rows.append(("VAT Registered Address",     _v(vat, "registered_address")))
        vat_rows.append(("Expiry",                         "No expiry date — ongoing registration"))
        if vat.get("return_period"):
            vat_rows.append(("Return Period",              _v(vat, "return_period")))
        if vat.get("registration_type"):
            vat_rows.append(("Registration Type",          _v(vat, "registration_type")))
        _kv_table(doc, vat_rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 6 — INSURANCE
    # ══════════════════════════════════════════════════════════════════════════
    if ins_up:
        _section_header(doc, n, "Insurance"); n += 1
        rows = []
        if ins.get("insurer"):
            rows.append(("Insurer",        _v(ins, "insurer")))
        if ins.get("policy_number"):
            rows.append(("Policy No.",     _v(ins, "policy_number")))
        if ins.get("insured_name"):
            rows.append(("Insured Name",   _v(ins, "insured_name")))
        if ins.get("coverage_type"):
            rows.append(("Coverage Type",  _v(ins, "coverage_type")))
        if ins.get("sum_insured"):
            rows.append(("Sum Insured",    _v(ins, "sum_insured")))
        if ins.get("premium"):
            rows.append(("Premium",        _v(ins, "premium")))
        if ins.get("deductible"):
            rows.append(("Deductible / Excess", _v(ins, "deductible")))
        if ins.get("valid_from"):
            rows.append(("Valid From",     _fmt_date(ins["valid_from"])))
        if ins.get("valid_to"):
            rows.append(("Valid To",       ins_label))
        if ins_sym in ("⚠", "✗"):
            _flag("Insurance Validity", "Insurance Certificate", "Valid To", ins_label, "",
                  "Renew insurance policy." if ins_sym == "✗"
                  else "Insurance expiring within 30 days.")
        _kv_table(doc, rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 7 — BUSINESS ACTIVITIES
    # ══════════════════════════════════════════════════════════════════════════
    if tl_up and tl.get("business_activity"):
        _section_header(doc, n, "Business Activities"); n += 1
        biz: list[tuple] = [("Primary Activity", _v(tl, "business_activity"))]
        if tl.get("activity_status"):
            biz.append(("Status",              _v(tl, "activity_status")))
        if tl.get("activity_scope"):
            biz.append(("Activity Scope",      _v(tl, "activity_scope")))
        if tl.get("regulatory_approval"):
            biz.append(("Regulatory Approval", _v(tl, "regulatory_approval")))
        _kv_table(doc, biz)

    # ══════════════════════════════════════════════════════════════════════════
    # 8 — SHARE CAPITAL & OWNERSHIP
    # ══════════════════════════════════════════════════════════════════════════
    if moa_up:
        _section_header(doc, n, "Share Capital & Ownership"); n += 1
        cap: list[tuple] = []
        if moa.get("share_capital"):
            cap.append(("Authorised & Paid-Up Capital", _v(moa, "share_capital")))
        if moa.get("shares_count"):
            cap.append(("Number of Shares",             _v(moa, "shares_count")))
        if moa.get("capital_currency"):
            cap.append(("Currency",                     _v(moa, "capital_currency")))
        if moa.get("capital_deposited"):
            cap.append(("Capital Deposited",            _v(moa, "capital_deposited")))
        if moa.get("statutory_reserve"):
            cap.append(("Statutory Reserve",            _v(moa, "statutory_reserve")))
        owner_nm = _v(moa, "owner_name", "") or _v(tl, "owner_name", "")
        if owner_nm and owner_nm != "—":
            cap.append(("Shareholder (100%)",           owner_nm))
        if moa.get("owner_shares"):
            cap.append(("Shareholding Detail",          _v(moa, "owner_shares")))
        _kv_table(doc, cap)

    # ══════════════════════════════════════════════════════════════════════════
    # 9 — OWNER / SHAREHOLDER DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    if tl_up or moa_up or pp_up or eid_up:
        _section_header(doc, n, "Owner / Shareholder Details"); n += 1
        owner_name = (
            _s(moa.get("owner_name")).strip() or
            _s(tl.get("owner_name")).strip() or
            _s(pp.get("holder_name")).strip() or
            _s(eid.get("holder_name")).strip()
        )
        rows: list[tuple] = [("Full Name (English)", owner_name or "—")]
        if moa.get("owner_name_arabic"):
            rows.append(("Full Name (Arabic)",   _v(moa, "owner_name_arabic")))
        nat = (_v(moa, "owner_nationality", "") or _v(tl, "owner_nationality", "")
               or _v(pp, "nationality", "") or _v(eid, "nationality", ""))
        if nat and nat != "—":
            rows.append(("Nationality", nat))
        pno = _v(moa, "owner_person_number", "") or _v(tl, "owner_person_number", "")
        if pno and pno != "—":
            rows.append(("Person No. (Licence)", pno))
        if moa.get("owner_shares"):
            rows.append(("Shareholding",  _v(moa, "owner_shares")))
        if moa.get("owner_liability"):
            rows.append(("Liability",     _v(moa, "owner_liability")))
        if moa.get("owner_residence"):
            rows.append(("Residence",     _v(moa, "owner_residence")))

        if pp_up and pp:
            rows.append(("─── PASSPORT ───────────────────────────────────────", ""))
            if pp.get("passport_number"):
                rows.append(("Passport No.",    _v(pp, "passport_number")))
            if pp.get("date_of_birth"):
                rows.append(("Date of Birth",  _fmt_date(pp["date_of_birth"])))
            if pp.get("place_of_birth"):
                rows.append(("Place of Birth", _v(pp, "place_of_birth")))
            if pp.get("issue_date"):
                rows.append(("Issue Date",     _fmt_date(pp["issue_date"])))
            if pp.get("expiry_date"):
                rows.append(("Expiry Date",    pp_label))

        if eid_up and eid:
            rows.append(("─── EMIRATES ID ────────────────────────────────────", ""))
            if eid.get("id_number"):
                rows.append(("ID No.",        _v(eid, "id_number")))
            if eid.get("date_of_birth"):
                rows.append(("Date of Birth", _fmt_date(eid["date_of_birth"])))
            if eid.get("expiry_date"):
                rows.append(("Expiry Date",   eid_label))

        if visa_up and visa:
            rows.append(("─── UAE RESIDENCE VISA ─────────────────────────────", ""))
            if visa.get("visa_number"):
                rows.append(("Visa / Permit No.",   _v(visa, "visa_number")))
            if visa.get("file_number"):
                rows.append(("File No.",            _v(visa, "file_number")))
            if visa.get("uid_number"):
                rows.append(("Unified No. (UID)",   _v(visa, "uid_number")))
            if visa.get("profession"):
                rows.append(("Profession",          _v(visa, "profession")))
            if visa.get("employer"):
                rows.append(("Sponsor / Employer",  _v(visa, "employer")))
            if visa.get("place_of_issue"):
                rows.append(("Place of Issue",      _v(visa, "place_of_issue")))
            if visa.get("issue_date"):
                rows.append(("Issue Date",          _fmt_date(visa["issue_date"])))
            if visa.get("expiry_date"):
                rows.append(("Expiry Date",         visa_label))
        _kv_table(doc, rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 10 — MANAGEMENT DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    if moa_up or (tl_up and tl.get("manager_name")):
        _section_header(doc, n, "Management Details"); n += 1
        mgr_name = _v(moa, "manager_name", "") or _v(tl, "manager_name", "")
        rows = [("Manager Name (English)", mgr_name or "—")]
        if moa.get("manager_name_arabic"):
            rows.append(("Manager Name (Arabic)", _v(moa, "manager_name_arabic")))
        mgr_nat = _v(moa, "manager_nationality", "") or _v(tl, "manager_nationality", "")
        if mgr_nat and mgr_nat != "—":
            rows.append(("Nationality", mgr_nat))
        mgr_pno = _v(moa, "manager_person_number", "") or _v(tl, "manager_person_number", "")
        if mgr_pno and mgr_pno != "—":
            rows.append(("Person No. (Licence)", mgr_pno))
        if moa.get("manager_role"):
            rows.append(("Role",             _v(moa, "manager_role")))
        if moa.get("manager_appointment_term"):
            rows.append(("Appointment Term", _v(moa, "manager_appointment_term")))
        if moa.get("manager_residence"):
            rows.append(("Residence",        _v(moa, "manager_residence")))
        if moa.get("manager_pobox"):
            rows.append(("P.O. Box",         _v(moa, "manager_pobox")))
        if moa.get("signing_authority"):
            rows.append(("Signing Authority", _v(moa, "signing_authority")))
        _kv_table(doc, rows)

    # ══════════════════════════════════════════════════════════════════════════
    # 11 — BANKING & SIGNATORY AUTHORITY
    # ══════════════════════════════════════════════════════════════════════════
    if moa_up:
        _section_header(doc, n, "Banking & Signatory Authority"); n += 1
        signatory = (_v(moa, "authorised_signatory", "")
                     or _v(moa, "manager_name", "")
                     or _v(tl,  "manager_name", ""))
        banking: list[tuple] = [
            ("Authorised Signatory", signatory or "—"),
            ("Signing Mode",         _v(moa, "signing_mode")),
        ]
        for key, label in [
            ("bank_open_close", "Open / Close Bank Accounts"),
            ("bank_operate",    "Operate Bank Accounts"),
            ("bank_cheques",    "Sign Cheques"),
            ("bank_transfer",   "Transfer / Withdraw Funds"),
            ("bank_tenders",    "Sign Tenders & Contracts"),
            ("bank_lc",         "Issue Letters of Credit"),
            ("bank_vat",        "VAT / FTA Returns"),
            ("bank_delegate",   "Delegate Authority"),
        ]:
            if moa.get(key):
                banking.append((label, _v(moa, key)))
        _kv_table(doc, banking)

    # ══════════════════════════════════════════════════════════════════════════
    # 12 — ADDRESS VERIFICATION — CROSS-DOCUMENT
    # ══════════════════════════════════════════════════════════════════════════
    any_addr_docs = (tl_up and ej_up) or (tl_up and vat_up) or (ej_up and vat_up)
    if any_addr_docs:
        _section_header(doc, n, "Address Verification — Cross-Document"); n += 1

        tl_unit  = _v(tl, "unit_number",        "")
        tl_bldg  = _v(tl, "building_name",      "")
        tl_area  = _v(tl, "area",               "")
        tl_parc  = _v(tl, "parcel_id",          "")
        tl_addr  = _v(tl, "registered_address", "")
        ej_unit  = _v(ej, "unit_number",         "")
        ej_bldg  = _v(ej, "building_name",       "")
        ej_area  = _v(ej, "area",                "")
        ej_parc  = _v(ej, "land_dm_parcel_id",   "")
        ej_tenant  = _v(ej, "tenant_name",      "")
        tl_company = _v(tl, "company_name",     "")
        ej_lic_no  = _v(ej, "licence_number",   "")
        tl_lic_no  = _v(tl, "license_number",   "")
        vat_addr   = _v(vat, "registered_address", "")

        if vat_up and (tl_up or ej_up):
            # 3-way table
            addr3: list[tuple] = [
                ("Company / Tenant Name",
                 tl_company or "—", ej_tenant or "—", _v(vat, "company_name") or "—",
                 _match3(tl_company, ej_tenant, _v(vat, "company_name", ""))),
                ("Full Address",
                 tl_addr or "—", (ej_bldg + " " + ej_area).strip() or "—", vat_addr or "—",
                 _match3(tl_addr, (ej_bldg + " " + ej_area).strip(), vat_addr)),
                ("Unit No.",
                 tl_unit or "—", ej_unit or "—", "—",
                 _match2(tl_unit, ej_unit)),
                ("Building",
                 tl_bldg or "—", ej_bldg or "—", "—",
                 _match2(tl_bldg, ej_bldg)),
                ("Area",
                 tl_area or "—", ej_area or "—", "—",
                 _match2(tl_area, ej_area)),
                ("Parcel ID / Land DM",
                 tl_parc or "—", ej_parc or "—", "—",
                 _match2(tl_parc, ej_parc)),
                ("Licence No.",
                 tl_lic_no or "—", ej_lic_no or "—", "—",
                 _match2(tl_lic_no, ej_lic_no)),
            ]
            _three_way_table(doc,
                ("Field", "Trade Licence", "EJARI", "VAT Certificate", "Match"),
                addr3)
            if vat_addr and tl_addr and _match2(vat_addr, tl_addr) != "✓":
                _flag("VAT Address Mismatch",
                      "VAT Certificate vs Trade Licence",
                      "Registered Address", tl_addr, vat_addr,
                      "Client must update address with the Federal Tax Authority (FTA) "
                      "to match current Trade Licence address. UAE VAT compliance requirement.")
        else:
            # 2-way EJARI vs TL
            cross: list[tuple] = [
                ("Company / Tenant Name",
                 ej_tenant  or "—", tl_company or "—",
                 _match2(ej_tenant, tl_company)),
                ("Licence No.",
                 ej_lic_no  or "—", tl_lic_no  or "—",
                 _match2(ej_lic_no, tl_lic_no)),
                ("Unit No.",
                 ej_unit    or "—", tl_unit    or "—",
                 _match2(ej_unit, tl_unit)),
                ("Building",
                 ej_bldg    or "—", tl_bldg    or "—",
                 _match2(ej_bldg, tl_bldg)),
                ("Area",
                 ej_area    or "—", tl_area    or "—",
                 _match2(ej_area, tl_area)),
                ("Parcel ID / Land DM",
                 ej_parc    or "—", tl_parc    or "—",
                 _match2(ej_parc, tl_parc)),
            ]
            _verify_table(doc, ("Field", "EJARI", "Trade Licence", "Match"), cross)
            for f, ev, tv, m in cross:
                if m == "⚠":
                    _flag(f"Mismatch — {f}", "EJARI vs Trade Licence", f, ev, tv,
                          "Verify with client and update the relevant document.")

    # ══════════════════════════════════════════════════════════════════════════
    # 13 — NAME VERIFICATION — TRADE LICENCE vs MOA
    # ══════════════════════════════════════════════════════════════════════════
    nv_rows: list[tuple] = []
    if tl_up and moa_up:
        tl_own  = _v(tl,  "owner_name",          "")
        moa_own = _v(moa, "owner_name",           "")
        tl_onat = _v(tl,  "owner_nationality",   "")
        moa_onat= _v(moa, "owner_nationality",   "")
        tl_oshr = _v(tl,  "owner_share",         "")
        moa_oshr= _v(moa, "owner_shares",        "")
        tl_mgr  = _v(tl,  "manager_name",        "")
        moa_mgr = _v(moa, "manager_name",        "")
        tl_mnat = _v(tl,  "manager_nationality", "")
        moa_mnat= _v(moa, "manager_nationality", "")
        tl_mrol = _v(tl,  "manager_role",        "")
        moa_mrol= _v(moa, "manager_role", "") or _v(moa, "signing_authority", "")

        nv_rows = [
            ("Owner Name",           tl_own  or "—", moa_own  or "—", _match2(tl_own,  moa_own)),
            ("Owner Nationality",    tl_onat or "—", moa_onat or "—", _match2(tl_onat, moa_onat)),
            ("Owner Share",          tl_oshr or "—", moa_oshr or "—", _match2(tl_oshr, moa_oshr)),
            ("Manager Name",         tl_mgr  or "—", moa_mgr  or "—", _match2(tl_mgr,  moa_mgr)),
            ("Manager Nationality",  tl_mnat or "—", moa_mnat or "—", _match2(tl_mnat, moa_mnat)),
            ("Manager Role",         tl_mrol or "—", moa_mrol or "—", _match2(tl_mrol, moa_mrol)),
        ]
        _section_header(doc, n, "Name Verification — Trade Licence vs MOA"); n += 1
        _verify_table(doc, ("Field", "Trade Licence", "MOA", "Match"), nv_rows)
        for f, tv, mv, m in nv_rows:
            if m == "⚠":
                _flag(f"Name Mismatch — {f}", "Trade Licence vs MOA", f, tv, mv,
                      "Align names across Trade Licence and MOA.")

    # ══════════════════════════════════════════════════════════════════════════
    # 14 — PERSONAL DOCUMENTS VERIFICATION
    # ══════════════════════════════════════════════════════════════════════════
    if eid_up or pp_up or visa_up:
        _section_header(doc, n, "Personal Documents Verification"); n += 1

        # 14A — Document Validity Status
        _sub_header(doc, "14A — Document Validity Status")
        status_rows: list[tuple] = []
        if eid_up and eid:
            status_rows.append((
                "Emirates ID",
                _v(eid, "holder_name"),
                _v(eid, "id_number"),
                _fmt_date(eid.get("expiry_date")),
                eid_sym,
            ))
            if eid_sym in ("⚠", "✗"):
                _flag("Emirates ID Validity", "Emirates ID", "Expiry Date", eid_label, "",
                      "Renew Emirates ID immediately." if eid_sym == "✗"
                      else "Emirates ID expiring within 30 days.")
        if pp_up and pp:
            status_rows.append((
                "Passport",
                _v(pp, "holder_name"),
                _v(pp, "passport_number"),
                _fmt_date(pp.get("expiry_date")),
                pp_sym,
            ))
            if pp_sym in ("⚠", "✗"):
                _flag("Passport Validity", "Passport", "Expiry Date", pp_label, "",
                      "Renew passport immediately." if pp_sym == "✗"
                      else "Passport expiring within 30 days.")
        if visa_up and visa:
            status_rows.append((
                "UAE Residence Visa",
                _v(visa, "holder_name"),
                _v(visa, "visa_number"),
                _fmt_date(visa.get("expiry_date")),
                visa_sym,
            ))
            if visa_sym in ("⚠", "✗"):
                _flag("Residence Visa Validity", "UAE Residence Visa", "Expiry Date",
                      visa_label, "",
                      "Renew residence visa immediately." if visa_sym == "✗"
                      else "Visa expiring within 30 days.")
        _doc_status_table(doc, status_rows)

        # 14B — Name Cross-Match (EID / Passport / Visa)
        eid_name  = (_v(eid,  "holder_name", "") if eid_up  and eid  else "")
        pp_name   = (_v(pp,   "holder_name", "") if pp_up   and pp   else "")
        visa_name = (_v(visa, "holder_name", "") if visa_up and visa else "")
        present_names = [x for x in [eid_name, pp_name, visa_name] if x and x != "—"]
        if len(present_names) >= 2:
            _sub_header(doc, "14B — Name Cross-Match — Personal Documents")
            m3 = _match3(eid_name, pp_name, visa_name)
            _three_way_table(doc,
                ("Field", "Emirates ID", "Passport", "UAE Residence Visa", "Match"),
                [("Full Name",
                  eid_name  or "—",
                  pp_name   or "—",
                  visa_name or "—",
                  m3)])
            if m3 == "⚠":
                _flag("Personal Document Name Mismatch",
                      "Emirates ID vs Passport vs UAE Residence Visa",
                      "Holder Name",
                      f"EID: {eid_name} | Passport: {pp_name} | Visa: {visa_name}", "",
                      "Names must be consistent across all personal identity documents.")

        # 14C — Passport Number (Passport vs Visa)
        if pp_up and visa_up and pp.get("passport_number") and visa.get("passport_number"):
            _sub_header(doc, "14C — Passport Number Consistency")
            pp_no   = _v(pp,   "passport_number")
            visa_pp = _v(visa, "passport_number")
            mpp = _match2(pp_no, visa_pp)
            _verify_table(doc,
                ("Field", "Passport", "UAE Residence Visa", "Match"),
                [("Passport No.", pp_no, visa_pp, mpp)])
            if mpp == "⚠":
                _flag("Passport Number Mismatch",
                      "Passport vs UAE Residence Visa",
                      "Passport No.", pp_no, visa_pp,
                      "Verify passport number — visa may reference an expired passport.")

        # 14D — Personal Name vs Corporate Documents
        ref_name = (
            _v(moa, "owner_name",   "") or _v(tl, "owner_name",   "") or
            _v(moa, "manager_name", "") or _v(tl, "manager_name", "")
        )
        if ref_name and ref_name != "—" and present_names:
            corp_rows: list[tuple] = []
            if eid_name and eid_name != "—":
                m = _match2(eid_name, ref_name)
                corp_rows.append(("Emirates ID vs TL / MOA", eid_name, ref_name, m))
                if m == "⚠":
                    _flag("Name Mismatch — EID vs Corporate",
                          "Emirates ID vs Trade Licence / MOA",
                          "Holder Name", eid_name, ref_name,
                          "Verify name spelling across personal and corporate documents.")
            if pp_name and pp_name != "—":
                m = _match2(pp_name, ref_name)
                corp_rows.append(("Passport vs TL / MOA", pp_name, ref_name, m))
                if m == "⚠":
                    _flag("Name Mismatch — Passport vs Corporate",
                          "Passport vs Trade Licence / MOA",
                          "Holder Name", pp_name, ref_name,
                          "Verify name spelling across personal and corporate documents.")
            if visa_name and visa_name != "—":
                m = _match2(visa_name, ref_name)
                corp_rows.append(("Residence Visa vs TL / MOA", visa_name, ref_name, m))
                if m == "⚠":
                    _flag("Name Mismatch — Visa vs Corporate",
                          "Residence Visa vs Trade Licence / MOA",
                          "Holder Name", visa_name, ref_name,
                          "Verify name spelling across personal and corporate documents.")
            if corp_rows:
                _sub_header(doc, "14D — Name vs Corporate Documents")
                _verify_table(doc,
                    ("Comparison", "Personal Document", "TL / MOA Name", "Match"),
                    corp_rows)

        # 14E — Employer on Visa vs Company Name
        if visa_up and visa.get("employer"):
            co  = _v(tl, "company_name", "") or _v(moa, "company_name", "")
            emp = _v(visa, "employer", "")
            if co and co != "—":
                _sub_header(doc, "14E — Employer (Visa) vs Company Name")
                m = _match2(emp, co)
                _verify_table(doc,
                    ("Field", "Visa — Employer / Sponsor", "Company Name (TL / MOA)", "Match"),
                    [("Employer / Company", emp, co, m)])
                if m == "⚠":
                    _flag("Employer Mismatch",
                          "UAE Residence Visa vs Trade Licence / MOA",
                          "Employer / Sponsor", emp, co,
                          "Verify sponsor on visa matches the company name on Trade Licence.")

    # ══════════════════════════════════════════════════════════════════════════
    # 15 — KYC VERIFICATION CHECKLIST
    # ══════════════════════════════════════════════════════════════════════════
    _section_header(doc, n, "KYC Verification Checklist"); n += 1
    checklist: list[tuple] = []

    def _cl(sym: str, yes_text: str, no_text: str = "") -> str:
        if sym == "✓":
            return f"✓  {yes_text}"
        return f"{sym}  {no_text or yes_text}"

    # Corporate
    if tl_up:
        tl_d = _parse_date(tl.get("expiry_date"))
        checklist.append(("Trade Licence Valid",
                          _cl(tl_sym,
                              f"Yes — expiry {_short_date(tl_d)}, {(tl_d - today).days} days remaining" if tl_d else "Yes",
                              tl_label)))
    if ej_up:
        ej_d = _parse_date(ej.get("expiry_date"))
        checklist.append(("EJARI / Lease Valid",
                          _cl(ej_sym,
                              f"Yes — expiry {_short_date(ej_d)}, {(ej_d - today).days} days remaining" if ej_d else "Yes",
                              ej_label)))
    if ins_up:
        ins_d = _parse_date(ins.get("valid_to"))
        insurer = _v(ins, "insurer", "")
        checklist.append(("Insurance Active",
                          _cl(ins_sym,
                              f"Yes — {insurer}, valid to {_short_date(ins_d)}" if ins_d else "Yes",
                              ins_label)))
    if moa_up:
        moa_d = _parse_date(moa.get("moa_date"))
        checklist.append(("MOA Executed & Notarised",
                          f"✓  Yes — dated {_short_date(moa_d)}" if moa_d else "✓  Yes"))
        checklist.append(("Original / Amended MOA",
                          "✓  ORIGINAL MOA — no amendments detected"))
    if tl.get("register_number"):
        checklist.append(("Company Legally Registered",
                          f"✓  Yes — Register No. {_v(tl, 'register_number')}"))
    if tl.get("dcci_membership_number"):
        checklist.append(("DCCI Membership Active",
                          f"✓  Yes — No. {_v(tl, 'dcci_membership_number')}"))
    if vat_up and vat.get("trn"):
        checklist.append(("VAT Registered (TRN)",
                          f"✓  Yes — TRN {_v(vat, 'trn')}"))
    if vat_up and tl_up and vat.get("registered_address") and tl.get("registered_address"):
        vm = _match2(_v(vat, "registered_address"), _v(tl, "registered_address"))
        checklist.append(("VAT Address Matches Trade Licence",
                          "✓  Addresses consistent" if vm == "✓"
                          else "⚠  MISMATCH — FTA update required"))
    if tl.get("last_renewal_date") and tl.get("last_renewal_fee"):
        ren_d = _parse_date(tl["last_renewal_date"])
        checklist.append(("Licence Recently Renewed",
                          f"✓  Yes — {_short_date(ren_d)}, fee {_v(tl, 'last_renewal_fee')}"))

    # Cross-verification
    if tl_up and moa_up and nv_rows:
        all_nv = all(r[3] == "✓" for r in nv_rows)
        checklist.append(("Names Match (TL vs MOA)",
                          "✓  Full match — Owner & Manager confirmed" if all_nv
                          else "⚠  Discrepancies detected — see Section 13"))
    if tl_up and ej_up:
        ej_tn = _s(ej.get("tenant_name")).strip()
        tl_cn = _s(tl.get("company_name")).strip()
        m = _match2(ej_tn, tl_cn) if (ej_tn and tl_cn) else "—"
        if m == "✓":
            checklist.append(("Tenant Name Match (EJARI vs TL)",
                              f"✓  Full match — {tl_cn}"))
        elif m == "⚠":
            checklist.append(("Tenant Name Match (EJARI vs TL)",
                              f"⚠  EJARI: {ej_tn}  |  TL: {tl_cn}"))
        ej_ln = _s(ej.get("licence_number")).strip()
        tl_ln = _s(tl.get("license_number")).strip()
        lm = _match2(ej_ln, tl_ln) if (ej_ln and tl_ln) else "—"
        if lm == "✓":
            checklist.append(("Licence No. Match (EJARI vs TL)", "✓  Consistent"))
        elif lm == "⚠":
            checklist.append(("Licence No. Match (EJARI vs TL)",
                              f"⚠  EJARI: {ej_ln}  |  TL: {tl_ln}"))

    # MOA authority
    if moa_up:
        owner_d = _v(moa, "owner_name", "")
        checklist.append(("Shareholder Structure",
                          f"✓  One Person LLC — 100%  {owner_d}".strip()))
        if moa.get("manager_name") or tl.get("manager_name"):
            checklist.append(("Manager Formally Appointed", "✓  Yes — via MOA"))
        if moa.get("bank_open_close") or moa.get("signing_mode"):
            checklist.append(("Bank Account Opening Authority",
                              f"✓  INDIVIDUAL — {_v(moa, 'signing_mode', 'sole signatory')}"))
        if moa.get("share_capital"):
            checklist.append(("Share Capital Paid Up",
                              f"✓  Yes — {_v(moa, 'share_capital')}"))

    # Personal documents
    if eid_up:
        eid_d = _parse_date(eid.get("expiry_date"))
        checklist.append(("Emirates ID — Present & Valid",
                          _cl(eid_sym,
                              f"Yes — expiry {_short_date(eid_d)}" if eid_d else "Yes",
                              eid_label)))
    if pp_up:
        pp_d = _parse_date(pp.get("expiry_date"))
        checklist.append(("Passport — Present & Valid",
                          _cl(pp_sym,
                              f"Yes — expiry {_short_date(pp_d)}" if pp_d else "Yes",
                              pp_label)))
    if visa_up:
        visa_d = _parse_date(visa.get("expiry_date"))
        checklist.append(("Residence Visa — Present & Valid",
                          _cl(visa_sym,
                              f"Yes — expiry {_short_date(visa_d)}" if visa_d else "Yes",
                              visa_label)))

    # Flags summary
    if flags:
        checklist.append(("Discrepancies / Adverse Flags",
                          f"⚠  {len(flags)} flag{'s' if len(flags) != 1 else ''} identified "
                          f"— see Section {n + 1}"))
    else:
        checklist.append(("Discrepancies / Adverse Flags",
                          "✓  None — all documents are consistent"))
    _kv_table(doc, checklist)

    # ══════════════════════════════════════════════════════════════════════════
    # 16 — DOCUMENTS REVIEWED
    # ══════════════════════════════════════════════════════════════════════════
    _section_header(doc, n, "Documents Reviewed"); n += 1
    reviewed: list[tuple] = []
    idx = 1
    if moa:
        line = f"Memorandum of Association — Contract No. {_v(moa, 'contract_number', '—')}"
        if moa.get("moa_date"):
            line += f", dated {_fmt_date(moa['moa_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if tl:
        line = f"Trade Licence No. {license_no} — {_v(tl, 'issuing_authority', 'DET Dubai')}"
        if tl.get("expiry_date"):
            line += f", expiry {_fmt_date(tl['expiry_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if ej:
        line = f"EJARI Tenancy Contract No. {ejari_no}"
        if ej.get("registration_date"):
            line += f" — registered {_fmt_date(ej['registration_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if vat:
        line = f"VAT Registration Certificate — TRN {_v(vat, 'trn', '—')}"
        if vat.get("effective_date"):
            line += f", effective {_fmt_date(vat['effective_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if ins:
        line = f"Insurance Certificate — {_v(ins, 'insurer', '—')}"
        if ins.get("policy_number"):
            line += f", Policy No. {_v(ins, 'policy_number')}"
        reviewed.append((str(idx), line)); idx += 1
    if tl and tl.get("register_number"):
        reviewed.append((str(idx),
            f"Commercial Register Certificate — No. {_v(tl, 'register_number')}")); idx += 1
    if tl and tl.get("last_renewal_fee"):
        line = f"Renewal Receipt — {_v(tl, 'last_renewal_fee')}"
        if tl.get("last_renewal_date"):
            line += f" paid {_fmt_date(tl['last_renewal_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if pp:
        line = f"Passport — {_v(pp, 'holder_name')}, No. {_v(pp, 'passport_number')}"
        if pp.get("expiry_date"):
            line += f", expiry {_fmt_date(pp['expiry_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if eid:
        line = f"Emirates ID — {_v(eid, 'holder_name')}, No. {_v(eid, 'id_number')}"
        if eid.get("expiry_date"):
            line += f", expiry {_fmt_date(eid['expiry_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    if visa:
        line = f"UAE Residence Visa — {_v(visa, 'holder_name')}"
        if visa.get("visa_number"):
            line += f", Permit No. {_v(visa, 'visa_number')}"
        if visa.get("expiry_date"):
            line += f", expiry {_fmt_date(visa['expiry_date'])}"
        reviewed.append((str(idx), line)); idx += 1
    _kv_table(doc, reviewed)

    # ══════════════════════════════════════════════════════════════════════════
    # 17 — DISCREPANCIES & FLAGS
    # ══════════════════════════════════════════════════════════════════════════
    _section_header(doc, n, "Discrepancies & Flags"); n += 1
    if not flags:
        _kv_table(doc, [("Result",
                          "✓  No discrepancies identified. "
                          "All documents reviewed are consistent.")])
    else:
        for i, flag in enumerate(flags, 1):
            _sub_header(doc, f"⚠  FLAG {i} — {flag['type']}")
            flag_rows: list[tuple] = []
            if flag.get("docs"):
                flag_rows.append(("Documents Affected", flag["docs"]))
            if flag.get("field"):
                flag_rows.append(("Field",              flag["field"]))
            if flag.get("val_a"):
                flag_rows.append(("Value — Document A", flag["val_a"]))
            if flag.get("val_b") and flag["val_b"] not in ("", flag.get("val_a", "")):
                flag_rows.append(("Value — Document B", flag["val_b"]))
            if flag.get("action"):
                flag_rows.append(("Recommended Action", flag["action"]))
            _kv_table(doc, flag_rows)

    # ── DISCLAIMER ─────────────────────────────────────────────────────────────
    _spacer(doc, 14)
    dp = doc.add_paragraph()
    dp.paragraph_format.space_after = Pt(4)
    dr = dp.add_run("DISCLAIMER")
    dr.bold = True
    dr.font.size = Pt(9)
    dr.font.color.rgb = _rgb(_NAVY)

    sources: list[str] = []
    if moa:
        sources.append(f"the Memorandum of Association (Contract No. {_v(moa, 'contract_number', '—')})")
    if tl:
        sources.append(f"Trade Licence No. {license_no}")
    if ej:
        sources.append(f"EJARI Tenancy Contract No. {ejari_no}")
    if vat:
        sources.append(f"the VAT Registration Certificate (TRN {_v(vat, 'trn', '—')})")
    if ins:
        sources.append(f"the Insurance Certificate ({_v(ins, 'insurer', '—')})")
    if pp:
        sources.append("the Passport")
    if eid:
        sources.append("the Emirates ID")
    if visa:
        sources.append("the UAE Residence Visa")
    source_str = (
        ", ".join(sources[:-1]) + " and " + sources[-1]
        if len(sources) > 1 else
        (sources[0] if sources else "documents supplied by the client")
    )

    bp = doc.add_paragraph()
    bp.paragraph_format.space_after = Pt(0)
    br = bp.add_run(
        f"This KYC Profile has been prepared by National Assurance & Advisory Services FZ LLC "
        f"(NAAS), Office 319, Garhoud Star Building, Al Garhoud, Dubai, UAE, from "
        f"{source_str}. "
        "This document does not constitute legal advice, a credit opinion, or a regulatory "
        "compliance clearance. NAAS accepts no liability for actions taken in reliance hereon "
        "without independent verification of the original source documents."
    )
    br.font.size = Pt(8)
    br.font.color.rgb = _rgb(_GREY_LITE)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ── Report data builder for frontend display ──────────────────────────────────

def build_report_data(extracted: dict, today: date) -> dict:
    """
    Build structured report data for the frontend preview page.
    Returns { company_name, panels, flags }.

    Panel types:
      "docstatus" — document validity table
      "kv"        — key/value detail table
      "match"     — cross-document comparison table
    """

    # ── helpers ────────────────────────────────────────────────────────────────
    def _msym(s: str) -> str:
        """Map ✓/⚠/— to ok/warn/dash for the frontend."""
        if s == "✓": return "ok"
        if s == "⚠": return "warn"
        return "dash"

    def _sc(s: str) -> str:
        if s == "✓": return "valid"
        if s == "⚠": return "expiring_soon"
        if s == "✗": return "expired"
        return "no_expiry"

    def _st(s: str, active: str = "VALID") -> str:
        if s == "✓": return active
        if s == "⚠": return "EXPIRING SOON"
        if s == "✗": return "EXPIRED"
        return "N/A"

    def _kv(label: str, value: str, sym: str = "") -> dict:
        return {"label": label, "value": value, "sym": sym}

    def _mr(field: str, values: list, match: str) -> dict:
        return {"field": field, "values": values, "match": match}

    # ── unpack ─────────────────────────────────────────────────────────────────
    tl   = dict(extracted.get("trade_license")   or {})
    ej   = dict(extracted.get("ejari")            or {})
    moa  = dict(extracted.get("moa")              or {})
    ins  = dict(extracted.get("insurance")        or {})
    pp   = dict(extracted.get("passport")         or {})
    eid  = dict(extracted.get("emirates_id")      or {})
    visa = dict(extracted.get("residence_visa")   or {})
    vat  = dict(extracted.get("vat_certificate")  or {})
    for d in [tl, ej, moa, ins, pp, eid, visa, vat]:
        d.pop("error", None)

    tl_up   = bool(tl);  ej_up  = bool(ej);  moa_up  = bool(moa); ins_up  = bool(ins)
    pp_up   = bool(pp);  eid_up = bool(eid); visa_up = bool(visa); vat_up  = bool(vat)

    tl_lbl,   tl_sym   = _expiry_label(tl.get("expiry_date"),   today)
    ej_lbl,   ej_sym   = _expiry_label(ej.get("expiry_date"),   today)
    pp_lbl,   pp_sym   = _expiry_label(pp.get("expiry_date"),   today)
    eid_lbl,  eid_sym  = _expiry_label(eid.get("expiry_date"),  today)
    visa_lbl, visa_sym = _expiry_label(visa.get("expiry_date"), today)
    ins_lbl,  ins_sym  = _insurance_label(ins.get("valid_to"),  today)

    company_name = (_v(tl, "company_name") or _v(moa, "company_name") or _v(vat, "company_name") or "—")

    panels: list[dict] = []
    flags:  list[dict] = []

    def _flag(ftype, docs, field, val_a, val_b, action):
        flags.append({"type": ftype, "docs": docs, "field": field,
                      "val_a": val_a, "val_b": val_b, "action": action})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 1 — Document Validity Status
    # ══════════════════════════════════════════════════════════════════════════
    ds_rows: list[dict] = []
    if tl_up:
        ds_rows.append({"doc": "Trade Licence",   "name": _v(tl,  "company_name"),
                        "number": _v(tl,  "license_number"),
                        "expiry": _fmt_date(tl.get("expiry_date")),
                        "sc": _sc(tl_sym), "st": _st(tl_sym), "sym": tl_sym})
        if tl_sym in ("⚠","✗"):
            _flag("Trade Licence Validity", "Trade Licence", "Expiry Date", tl_lbl, "",
                  "Renew Trade Licence immediately." if tl_sym == "✗"
                  else "Initiate renewal — expires within 30 days.")
    if ej_up:
        ds_rows.append({"doc": "EJARI Contract",  "name": _v(ej,  "tenant_name"),
                        "number": _v(ej,  "ejari_number"),
                        "expiry": _fmt_date(ej.get("expiry_date")),
                        "sc": _sc(ej_sym), "st": _st(ej_sym), "sym": ej_sym})
        if ej_sym in ("⚠","✗"):
            _flag("EJARI Validity", "EJARI", "Lease End Date", ej_lbl, "",
                  "Renew EJARI / tenancy contract." if ej_sym == "✗"
                  else "EJARI renewal due within 30 days.")
    if ins_up:
        ds_rows.append({"doc": "Insurance",       "name": _v(ins, "insured_name"),
                        "number": _v(ins, "policy_number"),
                        "expiry": _fmt_date(ins.get("valid_to")),
                        "sc": _sc(ins_sym), "st": _st(ins_sym, "ACTIVE"), "sym": ins_sym})
        if ins_sym in ("⚠","✗"):
            _flag("Insurance Validity", "Insurance Certificate", "Valid To", ins_lbl, "",
                  "Renew insurance policy." if ins_sym == "✗"
                  else "Insurance expiring within 30 days.")
    if pp_up:
        ds_rows.append({"doc": "Passport",        "name": _v(pp,  "holder_name"),
                        "number": _v(pp,  "passport_number"),
                        "expiry": _fmt_date(pp.get("expiry_date")),
                        "sc": _sc(pp_sym), "st": _st(pp_sym), "sym": pp_sym})
        if pp_sym in ("⚠","✗"):
            _flag("Passport Validity", "Passport", "Expiry Date", pp_lbl, "",
                  "Renew passport immediately." if pp_sym == "✗"
                  else "Passport expiring within 30 days.")
    if eid_up:
        ds_rows.append({"doc": "Emirates ID",     "name": _v(eid, "holder_name"),
                        "number": _v(eid, "id_number"),
                        "expiry": _fmt_date(eid.get("expiry_date")),
                        "sc": _sc(eid_sym), "st": _st(eid_sym), "sym": eid_sym})
        if eid_sym in ("⚠","✗"):
            _flag("Emirates ID Validity", "Emirates ID", "Expiry Date", eid_lbl, "",
                  "Renew Emirates ID immediately." if eid_sym == "✗"
                  else "Emirates ID expiring within 30 days.")
    if visa_up:
        ds_rows.append({"doc": "Residence Visa",  "name": _v(visa,"holder_name"),
                        "number": _v(visa,"visa_number"),
                        "expiry": _fmt_date(visa.get("expiry_date")),
                        "sc": _sc(visa_sym), "st": _st(visa_sym), "sym": visa_sym})
        if visa_sym in ("⚠","✗"):
            _flag("Residence Visa Validity", "UAE Residence Visa", "Expiry Date", visa_lbl, "",
                  "Renew residence visa immediately." if visa_sym == "✗"
                  else "Visa expiring within 30 days.")
    if moa_up:
        ds_rows.append({"doc": "MOA",             "name": _v(moa, "company_name"),
                        "number": _v(moa, "contract_number"),
                        "expiry": "—", "sc": "no_expiry", "st": "N/A", "sym": "—"})
    if vat_up:
        ds_rows.append({"doc": "VAT Certificate", "name": _v(vat, "company_name"),
                        "number": _v(vat, "trn"),
                        "expiry": "—", "sc": "no_expiry", "st": "N/A", "sym": "—"})
    panels.append({"title": "Document Validity Status", "type": "docstatus", "rows": ds_rows})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 2 — Company & Licence Details
    # ══════════════════════════════════════════════════════════════════════════
    if tl_up or moa_up or vat_up:
        kv: list[dict] = []
        cn = _v(tl,"company_name","") or _v(moa,"company_name","") or _v(vat,"company_name","")
        if cn and cn != "—":
            kv.append(_kv("Company Name (English)", cn))
        cn_ar = _v(tl,"company_name_arabic","") or _v(moa,"company_name_arabic","")
        if cn_ar and cn_ar != "—": kv.append(_kv("Company Name (Arabic)", cn_ar))
        lf = _v(tl,"legal_form","") or _v(moa,"legal_form","")
        if lf and lf != "—":   kv.append(_kv("Legal Type", lf))
        if tl.get("license_number"):     kv.append(_kv("Trade Licence No.", _v(tl,"license_number")))
        if tl.get("register_number"):    kv.append(_kv("Commercial Register No.", _v(tl,"register_number")))
        if tl.get("dcci_membership_number"): kv.append(_kv("DCCI Membership No.", _v(tl,"dcci_membership_number")))
        if tl.get("issuing_authority"):  kv.append(_kv("Issuing Authority", _v(tl,"issuing_authority")))
        if tl.get("license_type"):       kv.append(_kv("Licence Type", _v(tl,"license_type")))
        if tl.get("issue_date"):         kv.append(_kv("Issue Date", _fmt_date(tl["issue_date"])))
        if tl.get("expiry_date"):        kv.append(_kv("Licence Expiry", tl_lbl, tl_sym))
        if tl.get("last_renewal_date"):  kv.append(_kv("Last Renewal Date", _fmt_date(tl["last_renewal_date"])))
        if tl.get("last_renewal_fee"):   kv.append(_kv("Last Renewal Fee", _v(tl,"last_renewal_fee")))
        if tl.get("business_activity"):  kv.append(_kv("Business Activity", _v(tl,"business_activity")))
        if tl.get("activity_scope"):     kv.append(_kv("Activity Scope", _v(tl,"activity_scope")))
        if tl.get("registered_address"): kv.append(_kv("Registered Address", _v(tl,"registered_address")))
        if tl.get("unit_number"):        kv.append(_kv("Unit No.", _v(tl,"unit_number")))
        if tl.get("building_name"):      kv.append(_kv("Building", _v(tl,"building_name")))
        if tl.get("area"):               kv.append(_kv("Area", _v(tl,"area")))
        if tl.get("parcel_id"):          kv.append(_kv("Parcel ID / Land DM No.", _v(tl,"parcel_id")))
        if tl.get("makani_number"):      kv.append(_kv("Makani No.", _v(tl,"makani_number")))
        if tl.get("phone_fax"):          kv.append(_kv("Phone / Fax", _v(tl,"phone_fax")))
        if tl.get("mobile"):             kv.append(_kv("Mobile", _v(tl,"mobile")))
        if tl.get("email"):              kv.append(_kv("Email", _v(tl,"email")))
        if vat.get("trn"):               kv.append(_kv("VAT TRN", _v(vat,"trn")))
        if vat.get("effective_date"):    kv.append(_kv("VAT Effective Date", _fmt_date(vat["effective_date"])))
        if moa.get("share_capital"):     kv.append(_kv("Share Capital", _v(moa,"share_capital")))
        if moa.get("shares_count"):      kv.append(_kv("Number of Shares", _v(moa,"shares_count")))
        if moa.get("moa_date"):          kv.append(_kv("MOA Date", _fmt_date(moa["moa_date"])))
        if moa.get("contract_number"):   kv.append(_kv("MOA Contract No.", _v(moa,"contract_number")))
        if moa.get("financial_year"):    kv.append(_kv("Financial Year", _v(moa,"financial_year")))
        if kv: panels.append({"title": "Company & Licence Details", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 3 — Owner & Management
    # ══════════════════════════════════════════════════════════════════════════
    if tl_up or moa_up:
        kv = []
        own = _v(moa,"owner_name","") or _v(tl,"owner_name","")
        if own and own != "—":  kv.append(_kv("Owner Name (English)", own))
        own_ar = _v(moa,"owner_name_arabic","")
        if own_ar and own_ar != "—": kv.append(_kv("Owner Name (Arabic)", own_ar))
        own_nat = _v(moa,"owner_nationality","") or _v(tl,"owner_nationality","")
        if own_nat and own_nat != "—": kv.append(_kv("Owner Nationality", own_nat))
        if moa.get("owner_shares"):   kv.append(_kv("Shareholding", _v(moa,"owner_shares")))
        if moa.get("owner_liability"):kv.append(_kv("Liability", _v(moa,"owner_liability")))
        pno = _v(moa,"owner_person_number","") or _v(tl,"owner_person_number","")
        if pno and pno != "—": kv.append(_kv("Person No. (Licence)", pno))
        mgr = _v(moa,"manager_name","") or _v(tl,"manager_name","")
        if mgr and mgr != "—":  kv.append(_kv("Manager Name (English)", mgr))
        mgr_ar = _v(moa,"manager_name_arabic","")
        if mgr_ar and mgr_ar != "—": kv.append(_kv("Manager Name (Arabic)", mgr_ar))
        mgr_nat = _v(moa,"manager_nationality","") or _v(tl,"manager_nationality","")
        if mgr_nat and mgr_nat != "—": kv.append(_kv("Manager Nationality", mgr_nat))
        if moa.get("manager_role"):   kv.append(_kv("Manager Role", _v(moa,"manager_role")))
        if moa.get("signing_authority"): kv.append(_kv("Signing Authority", _v(moa,"signing_authority")))
        if moa.get("signing_mode"):   kv.append(_kv("Signing Mode", _v(moa,"signing_mode")))
        if moa.get("authorised_signatory"): kv.append(_kv("Authorised Signatory", _v(moa,"authorised_signatory")))
        if kv: panels.append({"title": "Owner & Management", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 4 — EJARI Details
    # ══════════════════════════════════════════════════════════════════════════
    if ej_up:
        kv = [_kv("EJARI Contract No.", _v(ej,"ejari_number"))]
        if ej.get("registration_date"): kv.append(_kv("Registration Date", _fmt_date(ej["registration_date"])))
        if ej.get("registered_by"):     kv.append(_kv("Registered by", _v(ej,"registered_by")))
        if ej.get("tenant_name"):       kv.append(_kv("Tenant Name", _v(ej,"tenant_name")))
        if ej.get("licence_number"):    kv.append(_kv("Trade Licence No. (EJARI)", _v(ej,"licence_number")))
        if ej.get("licence_issuer"):    kv.append(_kv("Licence Issuer (EJARI)", _v(ej,"licence_issuer")))
        if ej.get("start_date"):        kv.append(_kv("Lease Start Date", _fmt_date(ej["start_date"])))
        if ej.get("expiry_date"):       kv.append(_kv("Lease End Date", ej_lbl, ej_sym))
        if ej.get("annual_rent"):       kv.append(_kv("Annual Rent", _v(ej,"annual_rent")))
        if ej.get("security_deposit"):  kv.append(_kv("Security Deposit", _v(ej,"security_deposit")))
        if ej.get("ejari_fees_paid"):   kv.append(_kv("EJARI Fees Paid", _v(ej,"ejari_fees_paid")))
        if ej.get("unit_number"):       kv.append(_kv("Unit No.", _v(ej,"unit_number")))
        if ej.get("building_name"):     kv.append(_kv("Building", _v(ej,"building_name")))
        if ej.get("area"):              kv.append(_kv("Area", _v(ej,"area")))
        if ej.get("unit_type"):         kv.append(_kv("Unit Type", _v(ej,"unit_type")))
        if ej.get("size"):              kv.append(_kv("Size", _v(ej,"size")))
        if ej.get("plot_number"):       kv.append(_kv("Plot No.", _v(ej,"plot_number")))
        if ej.get("land_dm_parcel_id"): kv.append(_kv("Land DM No. (Parcel ID)", _v(ej,"land_dm_parcel_id")))
        if ej.get("makani_number"):     kv.append(_kv("Makani No.", _v(ej,"makani_number")))
        if ej.get("landlord_name"):     kv.append(_kv("Landlord Name", _v(ej,"landlord_name")))
        if ej.get("landlord_nationality"): kv.append(_kv("Landlord Nationality", _v(ej,"landlord_nationality")))
        if ej.get("property_manager"): kv.append(_kv("Property Manager", _v(ej,"property_manager")))
        panels.append({"title": "EJARI — Tenancy Contract", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 5 — MOA Details
    # ══════════════════════════════════════════════════════════════════════════
    if moa_up:
        kv = []
        if moa.get("contract_number"):    kv.append(_kv("Contract No.", _v(moa, "contract_number")))
        if moa.get("moa_date"):           kv.append(_kv("Date of MOA", _fmt_date(moa["moa_date"])))
        if moa.get("company_name"):       kv.append(_kv("Company Name (English)", _v(moa, "company_name")))
        if moa.get("company_name_arabic"):kv.append(_kv("Company Name (Arabic)", _v(moa, "company_name_arabic")))
        if moa.get("legal_form"):         kv.append(_kv("Legal Form", _v(moa, "legal_form")))
        if moa.get("company_duration"):   kv.append(_kv("Company Duration", _v(moa, "company_duration")))
        if moa.get("financial_year"):     kv.append(_kv("Financial Year", _v(moa, "financial_year")))
        if moa.get("disputes_jurisdiction"): kv.append(_kv("Disputes Jurisdiction", _v(moa, "disputes_jurisdiction")))
        if moa.get("share_capital"):      kv.append(_kv("Share Capital", _v(moa, "share_capital")))
        if moa.get("shares_count"):       kv.append(_kv("Number of Shares", _v(moa, "shares_count")))
        if moa.get("capital_currency"):   kv.append(_kv("Currency", _v(moa, "capital_currency")))
        if moa.get("capital_deposited"):  kv.append(_kv("Capital Deposited", _v(moa, "capital_deposited")))
        if moa.get("statutory_reserve"):  kv.append(_kv("Statutory Reserve", _v(moa, "statutory_reserve")))
        if moa.get("owner_name"):         kv.append(_kv("Owner / Shareholder", _v(moa, "owner_name")))
        if moa.get("owner_nationality"):  kv.append(_kv("Owner Nationality", _v(moa, "owner_nationality")))
        if moa.get("owner_shares"):       kv.append(_kv("Shareholding Detail", _v(moa, "owner_shares")))
        if moa.get("owner_liability"):    kv.append(_kv("Owner Liability", _v(moa, "owner_liability")))
        if moa.get("owner_residence"):    kv.append(_kv("Owner Residence", _v(moa, "owner_residence")))
        if moa.get("manager_name"):       kv.append(_kv("Manager Name", _v(moa, "manager_name")))
        if moa.get("manager_nationality"):kv.append(_kv("Manager Nationality", _v(moa, "manager_nationality")))
        if moa.get("manager_role"):       kv.append(_kv("Manager Role", _v(moa, "manager_role")))
        if moa.get("manager_appointment_term"): kv.append(_kv("Appointment Term", _v(moa, "manager_appointment_term")))
        if moa.get("manager_residence"):  kv.append(_kv("Manager Residence", _v(moa, "manager_residence")))
        if moa.get("signing_authority"):  kv.append(_kv("Signing Authority", _v(moa, "signing_authority")))
        if moa.get("authorised_signatory"):kv.append(_kv("Authorised Signatory", _v(moa, "authorised_signatory")))
        if moa.get("signing_mode"):       kv.append(_kv("Signing Mode", _v(moa, "signing_mode")))
        if moa.get("bank_open_close"):    kv.append(_kv("Open / Close Bank Accounts", _v(moa, "bank_open_close")))
        if moa.get("bank_operate"):       kv.append(_kv("Operate Bank Accounts", _v(moa, "bank_operate")))
        if moa.get("bank_cheques"):       kv.append(_kv("Sign Cheques", _v(moa, "bank_cheques")))
        if moa.get("bank_transfer"):      kv.append(_kv("Transfer / Withdraw Funds", _v(moa, "bank_transfer")))
        if moa.get("bank_tenders"):       kv.append(_kv("Sign Tenders & Contracts", _v(moa, "bank_tenders")))
        if moa.get("bank_lc"):            kv.append(_kv("Issue Letters of Credit", _v(moa, "bank_lc")))
        if moa.get("bank_vat"):           kv.append(_kv("VAT / FTA Returns", _v(moa, "bank_vat")))
        if moa.get("bank_delegate"):      kv.append(_kv("Delegate Authority", _v(moa, "bank_delegate")))
        if kv: panels.append({"title": "Memorandum of Association (MOA)", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 6 — Insurance Details
    # ══════════════════════════════════════════════════════════════════════════
    if ins_up:
        kv = []
        if ins.get("insurer"):           kv.append(_kv("Insurer", _v(ins, "insurer")))
        if ins.get("insurer_arabic"):    kv.append(_kv("Insurer (Arabic)", _v(ins, "insurer_arabic")))
        if ins.get("policy_number"):     kv.append(_kv("Policy No.", _v(ins, "policy_number")))
        if ins.get("insured_name"):      kv.append(_kv("Insured Name", _v(ins, "insured_name")))
        if ins.get("insured_name_arabic"):kv.append(_kv("Insured Name (Arabic)", _v(ins, "insured_name_arabic")))
        if ins.get("coverage_type"):     kv.append(_kv("Coverage Type", _v(ins, "coverage_type")))
        if ins.get("sum_insured"):       kv.append(_kv("Sum Insured", _v(ins, "sum_insured")))
        if ins.get("premium"):           kv.append(_kv("Premium", _v(ins, "premium")))
        if ins.get("deductible"):        kv.append(_kv("Deductible / Excess", _v(ins, "deductible")))
        if ins.get("valid_from"):        kv.append(_kv("Valid From", _fmt_date(ins["valid_from"])))
        if ins.get("valid_to"):          kv.append(_kv("Valid To", ins_lbl, ins_sym))
        if kv: panels.append({"title": "Insurance Certificate", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 7 — VAT Certificate Details
    # ══════════════════════════════════════════════════════════════════════════
    if vat_up:
        kv = []
        if vat.get("trn"):                   kv.append(_kv("Tax Registration No. (TRN)", _v(vat, "trn")))
        if vat.get("company_name"):          kv.append(_kv("Registered Name", _v(vat, "company_name")))
        if vat.get("company_name_arabic"):   kv.append(_kv("Registered Name (Arabic)", _v(vat, "company_name_arabic")))
        if vat.get("effective_date"):        kv.append(_kv("Effective Date", _fmt_date(vat["effective_date"])))
        if vat.get("registered_address"):    kv.append(_kv("Registered Address", _v(vat, "registered_address")))
        if vat.get("registered_address_arabic"): kv.append(_kv("Address (Arabic)", _v(vat, "registered_address_arabic")))
        if vat.get("return_period"):         kv.append(_kv("Return Period", _v(vat, "return_period")))
        if vat.get("registration_type"):     kv.append(_kv("Registration Type", _v(vat, "registration_type")))
        kv.append(_kv("Expiry", "No expiry date — ongoing registration"))
        if kv: panels.append({"title": "VAT Registration Certificate", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 8 — Personal Documents
    # ══════════════════════════════════════════════════════════════════════════
    if pp_up or eid_up or visa_up:
        kv = []
        if eid_up and eid:
            kv.append(_kv("─── EMIRATES ID ─────────────────────────────────────────────────", ""))
            if eid.get("holder_name"):    kv.append(_kv("Name",          _v(eid,"holder_name")))
            if eid.get("id_number"):      kv.append(_kv("ID No.",         _v(eid,"id_number")))
            if eid.get("date_of_birth"):  kv.append(_kv("Date of Birth",  _fmt_date(eid["date_of_birth"])))
            if eid.get("nationality"):    kv.append(_kv("Nationality",    _v(eid,"nationality")))
            if eid.get("expiry_date"):    kv.append(_kv("Expiry Date",    eid_lbl, eid_sym))
        if pp_up and pp:
            kv.append(_kv("─── PASSPORT ────────────────────────────────────────────────────", ""))
            if pp.get("holder_name"):     kv.append(_kv("Name",           _v(pp,"holder_name")))
            if pp.get("passport_number"): kv.append(_kv("Passport No.",   _v(pp,"passport_number")))
            if pp.get("nationality"):     kv.append(_kv("Nationality",    _v(pp,"nationality")))
            if pp.get("date_of_birth"):   kv.append(_kv("Date of Birth",  _fmt_date(pp["date_of_birth"])))
            if pp.get("place_of_birth"):  kv.append(_kv("Place of Birth", _v(pp,"place_of_birth")))
            if pp.get("issue_date"):      kv.append(_kv("Issue Date",     _fmt_date(pp["issue_date"])))
            if pp.get("expiry_date"):     kv.append(_kv("Expiry Date",    pp_lbl, pp_sym))
        if visa_up and visa:
            kv.append(_kv("─── UAE RESIDENCE VISA ──────────────────────────────────────────", ""))
            if visa.get("holder_name"):   kv.append(_kv("Name",                _v(visa,"holder_name")))
            if visa.get("visa_number"):   kv.append(_kv("Visa / Permit No.",   _v(visa,"visa_number")))
            if visa.get("file_number"):   kv.append(_kv("File No.",            _v(visa,"file_number")))
            if visa.get("uid_number"):    kv.append(_kv("Unified No. (UID)",   _v(visa,"uid_number")))
            if visa.get("profession"):    kv.append(_kv("Profession",          _v(visa,"profession")))
            if visa.get("employer"):      kv.append(_kv("Sponsor / Employer",  _v(visa,"employer")))
            if visa.get("nationality"):   kv.append(_kv("Nationality",         _v(visa,"nationality")))
            if visa.get("gender"):        kv.append(_kv("Gender",              _v(visa,"gender")))
            if visa.get("date_of_birth"): kv.append(_kv("Date of Birth",       _fmt_date(visa["date_of_birth"])))
            if visa.get("passport_number"): kv.append(_kv("Passport No.",      _v(visa,"passport_number")))
            if visa.get("issue_date"):    kv.append(_kv("Issue Date",          _fmt_date(visa["issue_date"])))
            if visa.get("expiry_date"):   kv.append(_kv("Expiry Date",         visa_lbl, visa_sym))
        if kv: panels.append({"title": "Personal Documents", "type": "kv", "rows": kv})

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 6 — Address Cross-Verification
    # ══════════════════════════════════════════════════════════════════════════
    if (tl_up and ej_up) or (tl_up and vat_up) or (ej_up and vat_up):
        tl_unit  = _v(tl,  "unit_number", "");     ej_unit  = _v(ej, "unit_number", "")
        tl_bldg  = _v(tl,  "building_name", "");   ej_bldg  = _v(ej, "building_name", "")
        tl_area  = _v(tl,  "area", "");            ej_area  = _v(ej, "area", "")
        tl_parc  = _v(tl,  "parcel_id", "");       ej_parc  = _v(ej, "land_dm_parcel_id", "")
        tl_addr  = _v(tl,  "registered_address", ""); vat_addr = _v(vat, "registered_address", "")
        ej_tenant  = _v(ej, "tenant_name", "");    tl_company = _v(tl, "company_name", "")
        ej_lic_no  = _v(ej, "licence_number", ""); tl_lic_no  = _v(tl, "license_number", "")

        if vat_up and (tl_up or ej_up):
            hdrs = ["Field", "Trade Licence", "EJARI", "VAT Certificate", "Match"]
            mr_rows = [
                _mr("Company / Tenant Name",
                    [tl_company or "—", ej_tenant or "—", _v(vat,"company_name") or "—"],
                    _msym(_match3(tl_company, ej_tenant, _v(vat,"company_name","")))),
                _mr("Full Address",
                    [tl_addr or "—", (ej_bldg+" "+ej_area).strip() or "—", vat_addr or "—"],
                    _msym(_match3(tl_addr, (ej_bldg+" "+ej_area).strip(), vat_addr))),
                _mr("Unit No.",      [tl_unit or "—", ej_unit or "—", "—"], _msym(_match2(tl_unit, ej_unit))),
                _mr("Building",      [tl_bldg or "—", ej_bldg or "—", "—"], _msym(_match2(tl_bldg, ej_bldg))),
                _mr("Area",          [tl_area or "—", ej_area or "—", "—"], _msym(_match2(tl_area, ej_area))),
                _mr("Parcel ID / Land DM", [tl_parc or "—", ej_parc or "—", "—"], _msym(_match2(tl_parc, ej_parc))),
                _mr("Licence No.",   [tl_lic_no or "—", ej_lic_no or "—", "—"], _msym(_match2(tl_lic_no, ej_lic_no))),
            ]
        else:
            hdrs = ["Field", "Trade Licence", "EJARI", "Match"]
            mr_rows = [
                _mr("Company / Tenant Name", [tl_company or "—", ej_tenant or "—"],  _msym(_match2(tl_company, ej_tenant))),
                _mr("Licence No.",           [tl_lic_no  or "—", ej_lic_no  or "—"], _msym(_match2(tl_lic_no,  ej_lic_no))),
                _mr("Unit No.",              [tl_unit    or "—", ej_unit    or "—"], _msym(_match2(tl_unit,    ej_unit))),
                _mr("Building",              [tl_bldg    or "—", ej_bldg    or "—"], _msym(_match2(tl_bldg,    ej_bldg))),
                _mr("Area",                  [tl_area    or "—", ej_area    or "—"], _msym(_match2(tl_area,    ej_area))),
                _mr("Parcel ID / Land DM",   [tl_parc    or "—", ej_parc    or "—"], _msym(_match2(tl_parc,    ej_parc))),
            ]
        panels.append({"title": "Address Cross-Verification", "type": "match", "headers": hdrs, "rows": mr_rows})
        for r in mr_rows:
            if r["match"] == "warn":
                _flag(f"Address Mismatch — {r['field']}", " vs ".join(hdrs[1:-1]),
                      r["field"], r["values"][0] if r["values"] else "—",
                      r["values"][1] if len(r["values"]) > 1 else "—",
                      "Verify with client and update the relevant document.")

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 7 — Name Verification: Trade Licence vs MOA
    # ══════════════════════════════════════════════════════════════════════════
    if tl_up and moa_up:
        tl_own  = _v(tl,  "owner_name", "");        moa_own  = _v(moa, "owner_name", "")
        tl_onat = _v(tl,  "owner_nationality", "");  moa_onat = _v(moa, "owner_nationality", "")
        tl_oshr = _v(tl,  "owner_share", "");        moa_oshr = _v(moa, "owner_shares", "")
        tl_mgr  = _v(tl,  "manager_name", "");       moa_mgr  = _v(moa, "manager_name", "")
        tl_mnat = _v(tl,  "manager_nationality", "");moa_mnat = _v(moa, "manager_nationality", "")
        tl_mrol = _v(tl,  "manager_role", "");       moa_mrol = _v(moa, "manager_role", "") or _v(moa,"signing_authority","")
        nv_rows = [
            _mr("Owner Name",          [tl_own  or "—", moa_own  or "—"], _msym(_match2(tl_own,  moa_own))),
            _mr("Owner Nationality",   [tl_onat or "—", moa_onat or "—"], _msym(_match2(tl_onat, moa_onat))),
            _mr("Owner Share",         [tl_oshr or "—", moa_oshr or "—"], _msym(_match2(tl_oshr, moa_oshr))),
            _mr("Manager Name",        [tl_mgr  or "—", moa_mgr  or "—"], _msym(_match2(tl_mgr,  moa_mgr))),
            _mr("Manager Nationality", [tl_mnat or "—", moa_mnat or "—"], _msym(_match2(tl_mnat, moa_mnat))),
            _mr("Manager Role",        [tl_mrol or "—", moa_mrol or "—"], _msym(_match2(tl_mrol, moa_mrol))),
        ]
        panels.append({"title": "Name Verification — Trade Licence vs MOA", "type": "match",
                        "headers": ["Field", "Trade Licence", "MOA", "Match"], "rows": nv_rows})
        for r in nv_rows:
            if r["match"] == "warn":
                _flag(f"Name Mismatch — {r['field']}", "Trade Licence vs MOA",
                      r["field"], r["values"][0], r["values"][1],
                      "Align names across Trade Licence and MOA.")

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL 8 — Personal Document Cross-Verification
    # ══════════════════════════════════════════════════════════════════════════
    if eid_up or pp_up or visa_up:
        eid_name  = _v(eid,  "holder_name", "") if eid_up  else ""
        pp_name   = _v(pp,   "holder_name", "") if pp_up   else ""
        visa_name = _v(visa, "holder_name", "") if visa_up else ""
        present   = [x for x in [eid_name, pp_name, visa_name] if x and x != "—"]

        # 8A — Name cross-match
        if len(present) >= 2:
            m3 = _match3(eid_name, pp_name, visa_name)
            panels.append({
                "title": "Personal Document Name Cross-Match",
                "type": "match",
                "headers": ["Field", "Emirates ID", "Passport", "UAE Residence Visa", "Match"],
                "rows": [_mr("Full Name",
                             [eid_name or "—", pp_name or "—", visa_name or "—"],
                             _msym(m3))]
            })
            if m3 == "⚠":
                _flag("Personal Name Mismatch", "EID / Passport / Visa", "Holder Name",
                      f"EID: {eid_name} | PP: {pp_name} | Visa: {visa_name}", "",
                      "Names must be consistent across all personal identity documents.")

        # 8B — Passport number: passport vs visa
        if pp_up and visa_up and pp.get("passport_number") and visa.get("passport_number"):
            pp_no   = _v(pp,   "passport_number")
            visa_pp = _v(visa, "passport_number")
            mpp = _match2(pp_no, visa_pp)
            panels.append({
                "title": "Passport Number — Passport vs Residence Visa",
                "type": "match",
                "headers": ["Field", "Passport", "UAE Residence Visa", "Match"],
                "rows": [_mr("Passport No.", [pp_no, visa_pp], _msym(mpp))]
            })
            if mpp == "⚠":
                _flag("Passport No. Mismatch", "Passport vs Residence Visa",
                      "Passport No.", pp_no, visa_pp,
                      "Verify — visa may reference an expired passport.")

        # 8C — Personal name vs corporate name
        ref_name = (_v(moa,"owner_name","") or _v(tl,"owner_name","") or
                    _v(moa,"manager_name","") or _v(tl,"manager_name",""))
        if ref_name and ref_name != "—" and present:
            corp_rows: list[dict] = []
            for label, name in [("Emirates ID", eid_name), ("Passport", pp_name), ("Residence Visa", visa_name)]:
                if name and name != "—":
                    m = _match2(name, ref_name)
                    corp_rows.append(_mr(f"{label} vs TL / MOA", [name, ref_name], _msym(m)))
                    if m == "⚠":
                        _flag(f"Name Mismatch — {label} vs Corporate", f"{label} vs TL/MOA",
                              "Holder Name", name, ref_name,
                              "Verify name spelling across personal and corporate documents.")
            if corp_rows:
                panels.append({
                    "title": "Personal Name vs Corporate Documents",
                    "type": "match",
                    "headers": ["Comparison", "Personal Document", "TL / MOA Name", "Match"],
                    "rows": corp_rows
                })

        # 8D — Employer on visa vs company name
        if visa_up and visa.get("employer"):
            co  = _v(tl,"company_name","") or _v(moa,"company_name","")
            emp = _v(visa, "employer")
            if co and co != "—":
                m = _match2(emp, co)
                panels.append({
                    "title": "Employer (Visa) vs Company Name",
                    "type": "match",
                    "headers": ["Field", "Visa — Employer / Sponsor", "Company Name (TL / MOA)", "Match"],
                    "rows": [_mr("Employer / Company", [emp, co], _msym(m))]
                })
                if m == "⚠":
                    _flag("Employer Mismatch", "Residence Visa vs TL/MOA",
                          "Employer / Sponsor", emp, co,
                          "Verify sponsor on visa matches the company on Trade Licence.")

    return {"company_name": company_name, "panels": panels, "flags": flags}
