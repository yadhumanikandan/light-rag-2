"""
NAAS v4.0 KYC compliance / analysis layer.

Pure-logic consumer of already-extracted KYC data. Produces validity,
cross-verification, MOA banking-authority assessment, presence/POA decision,
shareholder classification, attestation status, A-G checklist, and a typed
flag list.

Public entry point:

    analyse(extracted: dict, today: date) -> dict

No LLM calls, no DOCX writes, no I/O. Phases 3 (DOCX) and 4 (frontend) read
from the dict this returns.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.kyc_generator import _names_match, _s


# ── Date helpers ─────────────────────────────────────────────────────────────

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y")


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    txt = str(s).strip()
    if not txt:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", txt)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _validity_for(expiry: Any, today: date) -> dict | None:
    d = _parse_date(expiry)
    if d is None:
        return None
    days = (d - today).days
    if days < 0:
        status = "expired"
    elif days <= 30:
        status = "expiring_soon"
    else:
        status = "valid"
    return {"expiry_date": d.isoformat(), "days_remaining": days, "status": status}


# ── Step 2: validity ─────────────────────────────────────────────────────────

def _compute_validity(extracted: dict, today: date) -> dict:
    out: dict = {}

    pairs = [
        ("trade_license",     "expiry_date"),
        ("ejari",             "expiry_date"),
        ("insurance",         "valid_to"),
        ("emirates_id",       "expiry_date"),
        ("passport",          "expiry_date"),
        ("residence_visa",    "expiry_date"),
        ("free_zone_license", "expiry_date"),
        ("dcci_membership",   "expiry_date"),
    ]
    for key, field in pairs:
        node = extracted.get(key) or {}
        if isinstance(node, dict) and not node.get("error"):
            v = _validity_for(node.get(field), today)
            if v is not None:
                out[key] = v

    # VAT certificate has no expiry — registration is ongoing.
    vat = extracted.get("vat_certificate") or {}
    if isinstance(vat, dict) and vat and not vat.get("error"):
        out["vat_certificate"] = {
            "expiry_date": None,
            "days_remaining": None,
            "status": "ongoing",
            "note": "Ongoing registration — no expiry date",
        }

    # Board resolution: prefer explicit expiry_date, fall back to validity_until.
    br = extracted.get("board_resolution") or {}
    if isinstance(br, dict) and not br.get("error"):
        v = _validity_for(br.get("expiry_date") or br.get("validity_until"), today)
        if v is not None:
            out["board_resolution"] = v

    poa = extracted.get("poa") or {}
    if isinstance(poa, dict) and not poa.get("error"):
        v = _validity_for(poa.get("expiry_date") or poa.get("validity_until"), today)
        if v is not None:
            out["poa"] = v

    # Partner personal docs (multi-partner flow).
    partner_docs = extracted.get("partner_personal_docs") or []
    if isinstance(partner_docs, list):
        partner_validity = []
        for entry in partner_docs:
            if not isinstance(entry, dict):
                continue
            row = {"partner_name": _s(entry.get("partner_name", ""))}
            for sub_key in ("passport", "emirates_id", "residence_visa"):
                sub = entry.get(sub_key) or {}
                if isinstance(sub, dict) and not sub.get("error"):
                    v = _validity_for(sub.get("expiry_date"), today)
                    row[sub_key] = v
                else:
                    row[sub_key] = None
            partner_validity.append(row)
        if partner_validity:
            out["partner_personal_docs"] = partner_validity

    return out


# ── Step 3: cross-checks ─────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", _s(s).strip()).lower()


def _equal_norm(a: Any, b: Any) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na) and bool(nb) and na == nb


def _match_sym(values: list[str]) -> str:
    """For a row of values across docs: ✓ / ⚠ / — based on consistency."""
    present = [v for v in values if v and v != "—"]
    if not present:
        return "—"
    if len(present) == 1:
        return "—"
    base = present[0]
    for v in present[1:]:
        if not _names_match(base, v) and not _equal_norm(base, v):
            return "⚠"
    return "✓"


def _cross_check(extracted: dict) -> dict:
    tl   = extracted.get("trade_license")   or {}
    ej   = extracted.get("ejari")            or {}
    moa  = extracted.get("moa")              or {}
    vat  = extracted.get("vat_certificate")  or {}
    eid  = extracted.get("emirates_id")      or {}
    pp   = extracted.get("passport")         or {}
    visa = extracted.get("residence_visa")   or {}
    br   = extracted.get("board_resolution") or {}

    # Company name across TL / MOA / EJARI / VAT / EID employer / Visa employer.
    company_row = [
        ("trade_license",  _s(tl.get("company_name"))),
        ("moa",            _s(moa.get("company_name"))),
        ("ejari",          _s(ej.get("tenant_name"))),
        ("vat",            _s(vat.get("company_name"))),
        ("eid_employer",   _s(eid.get("employer", ""))),
        ("visa_employer",  _s(visa.get("employer", ""))),
    ]
    company_row = [(d, v) for d, v in company_row if v]
    company_match = _match_sym([v for _, v in company_row])

    # Address across TL / EJARI / VAT / MOA.
    ej_addr_parts = [_s(ej.get(k)) for k in ("building_name", "unit_number", "area") if ej.get(k)]
    addr_row = [
        ("trade_license",  _s(tl.get("registered_address"))),
        ("ejari",          " ".join(ej_addr_parts)),
        ("vat",            _s(vat.get("registered_address"))),
    ]
    addr_row = [(d, v) for d, v in addr_row if v]
    addr_match = _match_sym([v for _, v in addr_row])

    # Licence number TL vs EJARI vs VAT.
    licence_row = [
        ("trade_license",  _s(tl.get("license_number"))),
        ("ejari",          _s(ej.get("licence_number"))),
        ("br",             _s(br.get("licence_number"))),
    ]
    licence_row = [(d, v) for d, v in licence_row if v]
    licence_match = _match_sym([v for _, v in licence_row])

    # Person-name rows: known people from TL/MOA/Partners Annex.
    known_names: list[str] = []
    for n in (tl.get("owner_name"), tl.get("manager_name"), moa.get("owner_name"),
              moa.get("manager_name")):
        if n:
            known_names.append(_s(n))
    moa_shareholders = moa.get("shareholders") if isinstance(moa.get("shareholders"), list) else []
    for sh in moa_shareholders:
        if isinstance(sh, dict) and sh.get("name"):
            known_names.append(_s(sh["name"]))
    moa_managers = moa.get("managers") if isinstance(moa.get("managers"), list) else []
    for mg in moa_managers:
        if isinstance(mg, dict) and mg.get("name"):
            known_names.append(_s(mg["name"]))
    pa = extracted.get("partners_annex") or {}
    pa_partners = pa.get("partners") if isinstance(pa.get("partners"), list) else []
    for p in pa_partners:
        if isinstance(p, dict) and p.get("name"):
            known_names.append(_s(p["name"]))

    seen = set()
    unique_names: list[str] = []
    for n in known_names:
        key = _norm(n)
        if key and key not in seen:
            seen.add(key)
            unique_names.append(n)

    pp_name   = _s(pp.get("holder_name"))
    eid_name  = _s(eid.get("holder_name"))
    visa_name = _s(visa.get("holder_name"))
    br_name   = _s(br.get("signatory_name"))

    person_rows: list[dict] = []
    for n in unique_names:
        row_vals = {
            "name":            n,
            "passport":        pp_name   if pp_name   and _names_match(n, pp_name)   else "",
            "emirates_id":     eid_name  if eid_name  and _names_match(n, eid_name)  else "",
            "residence_visa":  visa_name if visa_name and _names_match(n, visa_name) else "",
            "board_resolution": br_name  if br_name   and _names_match(n, br_name)   else "",
        }
        present_for_n = [v for k, v in row_vals.items() if k != "name" and v]
        if not present_for_n:
            row_vals["match"] = "—"
        else:
            row_vals["match"] = _match_sym([n] + present_for_n)
        person_rows.append(row_vals)

    # DOB: EID vs Passport.
    dob_row = {
        "eid":      _s(eid.get("date_of_birth")),
        "passport": _s(pp.get("date_of_birth")),
    }
    dob_match = _match_sym([v for v in dob_row.values() if v])

    # Passport No.: Passport vs Visa vs MOA.
    pp_num_row = {
        "passport":         _s(pp.get("passport_number")),
        "residence_visa":   _s(visa.get("passport_number")),
        "moa":              _s(moa.get("owner_passport_number") or ""),
    }
    pp_match = _match_sym([v for v in pp_num_row.values() if v])

    # Employer: EID employer / Visa employer vs TL company name.
    employer_row = {
        "trade_license_company": _s(tl.get("company_name")),
        "eid_employer":          _s(eid.get("employer", "")),
        "visa_employer":         _s(visa.get("employer", "")),
    }
    employer_match = _match_sym([v for v in employer_row.values() if v])

    return {
        "company_name":    {"values": company_row,    "match": company_match},
        "addresses":       {"values": addr_row,       "match": addr_match},
        "licence_number":  {"values": licence_row,    "match": licence_match},
        "person_names":    person_rows,
        "dob":             {"values": dob_row,        "match": dob_match},
        "passport_number": {"values": pp_num_row,     "match": pp_match},
        "employer":        {"values": employer_row,   "match": employer_match},
    }


# ── Step 4: MOA banking-authority assessment ─────────────────────────────────

_BANKING_PHRASES = {
    "open_close_accounts": [
        "open and close", "open or close", "open accounts", "close accounts",
        "open bank account", "open a bank account",
    ],
    "sign_cheques": [
        "sign cheque", "sign cheques", "sign checks", "issue cheque",
        "draw cheque",
    ],
    "transfer_withdraw_funds": [
        "transfer fund", "withdraw fund", "transfer money", "withdraw money",
        "transfer and withdraw", "make transfer",
    ],
    "delegate_via_poa": [
        "delegate", "power of attorney", "authorise third party",
        "authorize third party", "appoint attorney",
    ],
}


def _bool_or_text(val: Any, phrases: list[str]) -> bool | None:
    """True/False/None for a banking-authority field that may be either a
    boolean (Phase 2 structured field) or free text (current extractor)."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    text = _s(val).lower()
    if not text:
        return None
    if any(p in text for p in phrases):
        return True
    return False


def _assess_moa_authority(extracted: dict) -> dict:
    moa = extracted.get("moa") or {}
    if not moa or moa.get("error"):
        return {
            "sufficient": False,
            "signing_mode": "unknown",
            "powers": {
                "open_close_accounts": None,
                "sign_cheques": None,
                "transfer_withdraw_funds": None,
                "delegate_via_poa": None,
            },
            "named_signatory": None,
            "resolution_required": True,
            "reason": "MOA not provided",
        }

    # Phase 2 will add a structured "banking_authority" block. Read from it
    # if present, else fall back to best-effort parsing of free-text fields.
    ba = moa.get("banking_authority") if isinstance(moa.get("banking_authority"), dict) else None
    if ba:
        powers = ba.get("powers") or {}
        powers_out = {
            "open_close_accounts":     powers.get("open_close_accounts"),
            "sign_cheques":            powers.get("sign_cheques"),
            "transfer_withdraw_funds": powers.get("transfer_withdraw_funds"),
            "delegate_via_poa":        powers.get("delegate_via_poa"),
        }
        explicit = bool(ba.get("explicitly_granted"))
        signing_mode = ba.get("signing_mode") or "unknown"
        named = ba.get("named_signatory") or None
    else:
        powers_out = {
            "open_close_accounts":     _bool_or_text(moa.get("bank_open_close"),
                                                    _BANKING_PHRASES["open_close_accounts"]),
            "sign_cheques":            _bool_or_text(moa.get("bank_cheques"),
                                                    _BANKING_PHRASES["sign_cheques"]),
            "transfer_withdraw_funds": _bool_or_text(moa.get("bank_transfer"),
                                                    _BANKING_PHRASES["transfer_withdraw_funds"]),
            "delegate_via_poa":        _bool_or_text(moa.get("bank_delegate"),
                                                    _BANKING_PHRASES["delegate_via_poa"]),
        }
        explicit = any(v is True for v in powers_out.values())
        sm = _s(moa.get("signing_mode")).lower()
        if "joint" in sm:
            signing_mode = "joint"
        elif "individual" in sm or "sole" in sm:
            signing_mode = "individual"
        else:
            signing_mode = "unknown"
        named = (
            moa.get("authorised_signatory")
            or moa.get("manager_name")
            or (moa.get("managers") or [{}])[0].get("name") if isinstance(moa.get("managers"), list) and moa.get("managers") else None
            or moa.get("owner_name")
        )

    sufficient = bool(explicit) and bool(named)

    # If MOA names a different manager than the BR signatory, an updated
    # resolution is required even when MOA is otherwise sufficient.
    br = extracted.get("board_resolution") or {}
    br_signatory = _s(br.get("signatory_name"))
    moa_manager = _s(named or "")
    signatory_differs = bool(br_signatory) and bool(moa_manager) and not _names_match(
        br_signatory, moa_manager
    )

    # Spec 5B row 5: Manager has changed since the MOA was signed (TL manager
    # ≠ MOA manager). Detect this even when no BR has been uploaded.
    tl = extracted.get("trade_license") or {}
    tl_manager = _s(tl.get("manager_name"))
    manager_changed = (
        bool(tl_manager) and bool(moa_manager)
        and not _names_match(tl_manager, moa_manager)
    )

    if not sufficient:
        reason = "MOA silent on banking authority" if not explicit else "No named signatory"
    elif signatory_differs:
        reason = "Current BR signatory differs from MOA-named manager"
    elif manager_changed:
        reason = (f"Current Trade Licence manager ({tl_manager}) "
                  f"differs from MOA-named manager ({moa_manager})")
    else:
        reason = "MOA grants explicit banking authority to a named signatory"

    return {
        "sufficient":          sufficient and not signatory_differs and not manager_changed,
        "signing_mode":        signing_mode,
        "powers":              powers_out,
        "named_signatory":     _s(named) or None,
        "resolution_required": (not sufficient) or signatory_differs or manager_changed,
        "reason":              reason,
        "manager_changed":     manager_changed,
        "tl_manager":          tl_manager or None,
    }


# ── Step 5: presence / POA ───────────────────────────────────────────────────

def _find_personal_docs(extracted: dict, person_name: str) -> dict:
    """Locate EID/Passport/Visa nodes for a named person. Looks in
    partner_personal_docs first, then the top-level singletons."""
    out = {"emirates_id": None, "passport": None, "residence_visa": None}
    if not person_name:
        return out

    partner_docs = extracted.get("partner_personal_docs") or []
    for entry in partner_docs if isinstance(partner_docs, list) else []:
        if not isinstance(entry, dict):
            continue
        if _names_match(person_name, _s(entry.get("partner_name"))):
            for k in out:
                d = entry.get(k)
                if isinstance(d, dict) and not d.get("error"):
                    out[k] = d
            return out

    for k, holder_field in (
        ("emirates_id",    "holder_name"),
        ("passport",       "holder_name"),
        ("residence_visa", "holder_name"),
    ):
        node = extracted.get(k) or {}
        if isinstance(node, dict) and not node.get("error"):
            if _names_match(person_name, _s(node.get(holder_field, ""))):
                out[k] = node
    return out


def _doc_validity_status(node: dict | None, today: date, field: str = "expiry_date") -> str:
    if not node:
        return "missing"
    v = _validity_for(node.get(field), today)
    return v["status"] if v else "missing"


def _check_presence(extracted: dict, today: date, moa_authority: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    # Collect candidate signatories with their roles.
    candidates: list[tuple[str, str]] = []

    moa = extracted.get("moa") or {}
    if moa_authority.get("named_signatory"):
        candidates.append((moa_authority["named_signatory"], "MOA-named signatory"))
    moa_managers = moa.get("managers") if isinstance(moa.get("managers"), list) else []
    for mg in moa_managers:
        if isinstance(mg, dict) and mg.get("name"):
            candidates.append((_s(mg["name"]), _s(mg.get("role")) or "Manager"))
    if moa.get("manager_name"):
        candidates.append((_s(moa["manager_name"]), "Manager"))
    if moa.get("owner_name"):
        candidates.append((_s(moa["owner_name"]), "Owner"))

    br = extracted.get("board_resolution") or {}
    if br.get("signatory_name"):
        candidates.append((_s(br["signatory_name"]),
                           _s(br.get("signatory_designation")) or "BR signatory"))

    poa = extracted.get("poa") or {}
    if poa.get("grantee_name"):
        candidates.append((_s(poa["grantee_name"]), "POA grantee"))
    if poa.get("grantor_name"):
        candidates.append((_s(poa["grantor_name"]), "POA grantor"))

    for name, role in candidates:
        if not name:
            continue
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)

        docs = _find_personal_docs(extracted, name)
        eid_status   = _doc_validity_status(docs["emirates_id"], today)
        visa_status  = _doc_validity_status(docs["residence_visa"], today)
        pp_status    = _doc_validity_status(docs["passport"], today)

        eid_valid  = eid_status == "valid"
        visa_valid = visa_status == "valid"
        pp_valid   = pp_status == "valid"
        in_uae     = visa_valid

        can_proceed = eid_valid and visa_valid and pp_valid and in_uae

        # Pick first remediation action.
        if can_proceed:
            action = "None"
        elif not in_uae:
            if visa_status == "missing":
                action = "Travel to UAE / arrange POA"
            else:
                action = f"Renew Residence Visa ({visa_status})"
        elif eid_status != "valid":
            action = ("Upload Emirates ID" if eid_status == "missing"
                      else f"Renew Emirates ID ({eid_status})")
        elif pp_status != "valid":
            action = ("Upload Passport" if pp_status == "missing"
                      else f"Renew Passport ({pp_status})")
        else:
            action = "Provide POA"

        rows.append({
            "person":         name,
            "role":           role,
            "in_uae":         in_uae,
            "eid_status":     eid_status,
            "eid_valid":      eid_valid,
            "passport_status": pp_status,
            "passport_valid": pp_valid,
            "visa_status":    visa_status,
            "visa_valid":     visa_valid,
            "can_proceed":    can_proceed,
            "action":         action,
        })

    return rows


# ── Step 6: shareholder classification ───────────────────────────────────────

_CORPORATE_SUFFIXES = (
    "llc", "l.l.c", "ltd", "limited", "pjsc", "psc", "dmcc", "sarl",
    "gmbh", "inc", "corp", "co.", "company", "establishment", "fz",
    "fzco", "fz-llc", "holding", "ag", "s.a.", "s.a", "s.a.s",
)


def _looks_corporate(name: str) -> bool:
    n = name.lower()
    return any(suffix in n for suffix in _CORPORATE_SUFFIXES)


def _classify_shareholders(extracted: dict) -> list[dict]:
    pa = extracted.get("partners_annex") or {}
    pa_list = pa.get("partners") if isinstance(pa.get("partners"), list) else []

    moa = extracted.get("moa") or {}
    moa_list = moa.get("shareholders") if isinstance(moa.get("shareholders"), list) else []

    source = pa_list or moa_list
    out: list[dict] = []

    for entry in source:
        if not isinstance(entry, dict):
            continue
        name = _s(entry.get("name"))
        if not name:
            continue

        # Prefer explicit is_corporate flag (Phase 2 partners_annex).
        is_corp_flag = entry.get("is_corporate")
        person_no = _s(entry.get("person_number"))
        if is_corp_flag is True:
            ptype = "corporate"
        elif is_corp_flag is False:
            ptype = "natural"
        elif _looks_corporate(name) or not person_no:
            ptype = "corporate" if _looks_corporate(name) else "natural"
            # If lacks a person number AND looks corporate → corporate.
            # Plain individual without person number is still treated as natural.
            if not _looks_corporate(name) and not person_no and not entry.get("nationality"):
                ptype = "corporate"
        else:
            ptype = "natural"

        out.append({
            "name":          name,
            "type":          ptype,
            "share_pct":     _s(entry.get("share_percentage") or entry.get("shares")),
            "nationality":   _s(entry.get("nationality")),
            "jurisdiction":  _s(entry.get("jurisdiction")) or None,
            "person_number": person_no or None,
        })

    if out:
        return out

    # Fallback: trade licence single owner.
    tl = extracted.get("trade_license") or {}
    if tl.get("owner_name"):
        name = _s(tl["owner_name"])
        out.append({
            "name":          name,
            "type":          "corporate" if _looks_corporate(name) else "natural",
            "share_pct":     _s(tl.get("owner_share")),
            "nationality":   _s(tl.get("owner_nationality")),
            "jurisdiction":  None,
            "person_number": _s(tl.get("owner_person_number")) or None,
        })
    return out


# ── Step 7: corporate shareholder KYC checklist ──────────────────────────────

# Spec 7A — corporate shareholder owns 100%.
_CORPORATE_DOCS_100 = [
    "Certificate of Incorporation",
    "Memorandum & Articles of Association (corporate)",
    "Register of Shareholders",
    "Register of Directors",
    "Certificate of Good Standing",
    "Board Resolution authorising the UAE investment",
    "Specimen signatures of directors",
    "Audited financial statements (last 2 years)",
    "Ultimate Beneficial Owner (UBO) declaration",
    "Attested corporate KYC pack (4-stage chain)",
]

# Spec 7B — corporate co-partner.
_CORPORATE_DOCS_PARTNER = [
    "Certificate of Incorporation",
    "Memorandum & Articles of Association (corporate)",
    "Register of Shareholders",
    "Register of Directors",
    "Certificate of Good Standing",
    "Board Resolution authorising the UAE investment",
    "Ultimate Beneficial Owner (UBO) declaration",
    "Attested corporate KYC pack (4-stage chain)",
]


def _share_pct_to_float(s: str) -> float | None:
    if not s:
        return None
    m = re.findall(r"(\d+(?:\.\d+)?)", str(s))
    if not m:
        return None
    try:
        return float(m[-1])
    except ValueError:
        return None


# Map extractor keys to checklist labels (Phase 2 surfaces these).
_CORPORATE_DOC_LABELS = {
    "certificate_of_incorporation": "Certificate of Incorporation",
    "register_of_shareholders":     "Register of Shareholders",
    "register_of_directors":        "Register of Directors",
    "certificate_of_good_standing": "Certificate of Good Standing",
    "corporate_moa_aoa":            "Memorandum & Articles of Association (corporate)",
    "audited_financials":           "Audited financial statements (last 2 years)",
    "ubo_declaration":              "Ultimate Beneficial Owner (UBO) declaration",
    "specimen_signatures":          "Specimen signatures of directors",
}


def _merge_attestation(blocks: list[dict]) -> dict:
    """OR-merge attestation booleans across multiple docs. true wins, then false,
    null only if every block is null/absent for that key."""

    def _merge_bool(values: list) -> bool | None:
        if any(v is True for v in values):
            return True
        if any(v is False for v in values):
            return False
        return None

    s1_present = _merge_bool([(b.get("stage1_translation") or {}).get("present") for b in blocks])
    s2_notary = _merge_bool([(b.get("stage2_home_country") or {}).get("notary") for b in blocks])
    s2_mfa = _merge_bool([(b.get("stage2_home_country") or {}).get("mfa") for b in blocks])
    s2_apost = _merge_bool([(b.get("stage2_home_country") or {}).get("apostille") for b in blocks])
    s3_present = _merge_bool([(b.get("stage3_uae_embassy") or {}).get("present") for b in blocks])
    s4_present = _merge_bool([(b.get("stage4_uae_mofa") or {}).get("present") for b in blocks])

    return {
        "stage1_translation":  {"present": s1_present},
        "stage2_home_country": {"notary": s2_notary, "mfa": s2_mfa, "apostille": s2_apost},
        "stage3_uae_embassy":  {"present": s3_present},
        "stage4_uae_mofa":     {"present": s4_present},
    }


# Spec 7E — country-specific attestation chains. Routes return a list of
# stages the document must pass through, in order. The list always terminates
# with UAE MOFA counter-attestation on UAE soil.
#
# Hague Apostille countries get a shorter Stage-2 (single Apostille certificate).
# Non-Hague countries need notary → home MFA → UAE Embassy explicitly.

_HAGUE_COUNTRIES = {
    "united kingdom", "uk", "great britain", "england", "scotland", "wales",
    "luxembourg", "germany", "france", "italy", "spain", "netherlands",
    "belgium", "switzerland", "austria", "portugal", "greece", "ireland",
    "denmark", "sweden", "norway", "finland", "poland", "czech republic",
    "hungary", "australia", "new zealand", "japan", "south korea", "korea",
    "south africa", "mexico", "brazil", "argentina", "russia", "turkey",
    "cyprus", "malta", "estonia", "latvia", "lithuania", "slovenia", "slovakia",
    "croatia", "bulgaria", "romania",
}

_COUNTRY_ROUTES = {
    "united kingdom": ["Certified English translation",
                       "Apostille (UK FCDO)",
                       "UAE Embassy London legalisation",
                       "UAE MOFA counter-attestation"],
    "united states":  ["Certified English translation",
                       "State Notary Public",
                       "State MFA / Secretary of State",
                       "UAE Embassy (Washington / NY / LA) legalisation",
                       "UAE MOFA counter-attestation"],
    "india":          ["Certified English translation",
                       "Notary Public (India)",
                       "MEA (Ministry of External Affairs) attestation",
                       "UAE Embassy (New Delhi / Mumbai / Chennai) legalisation",
                       "UAE MOFA counter-attestation"],
    "iran":           ["Certified English translation",
                       "Notary Public (Iran)",
                       "MFA Iran attestation (no Apostille)",
                       "UAE Embassy Tehran legalisation",
                       "UAE MOFA counter-attestation"],
    "china":          ["Certified English translation",
                       "CCPIT or Notary Office (China)",
                       "MFA China attestation",
                       "UAE Embassy (Beijing / Shanghai) legalisation",
                       "UAE MOFA counter-attestation"],
    "pakistan":       ["Certified English translation",
                       "Notary Public (Pakistan)",
                       "MOFA Pakistan attestation",
                       "UAE Embassy (Islamabad / Karachi) legalisation",
                       "UAE MOFA counter-attestation"],
    "saudi arabia":   ["Certified English translation",
                       "MFA KSA attestation",
                       "UAE Embassy Riyadh legalisation",
                       "UAE MOFA counter-attestation"],
    "luxembourg":     ["Certified English translation",
                       "Apostille (Luxembourg)",
                       "UAE Embassy legalisation",
                       "UAE MOFA counter-attestation"],
}


def _attestation_path_for(country: str | None) -> dict:
    """Return the attestation chain for a given home jurisdiction.

    Output: {
      "country": <normalised country>,
      "is_hague": bool | None,
      "stages": [<ordered chain>],
      "notes": <free text caveats>,
    }
    """
    if not country:
        return {
            "country": None,
            "is_hague": None,
            "stages": [
                "Certified English translation",
                "Home country Notary + MFA attestation OR Apostille (Hague countries only)",
                "UAE Embassy legalisation in country of origin",
                "UAE MOFA counter-attestation in UAE",
            ],
            "notes": "Jurisdiction not stated; default 4-stage chain applies.",
        }
    norm = country.strip().lower()
    # Direct match.
    if norm in _COUNTRY_ROUTES:
        return {
            "country":  country,
            "is_hague": norm in _HAGUE_COUNTRIES,
            "stages":   _COUNTRY_ROUTES[norm],
            "notes":    None,
        }
    # Hague fallback (Apostille flow).
    if any(norm == h or norm in h or h in norm for h in _HAGUE_COUNTRIES):
        return {
            "country":  country,
            "is_hague": True,
            "stages": [
                "Certified English translation",
                f"Apostille issued in {country}",
                "UAE Embassy legalisation in country of origin",
                "UAE MOFA counter-attestation in UAE",
            ],
            "notes": "Hague Convention country — Apostille satisfies Stage 2.",
        }
    # GCC bilateral fallback.
    if norm in ("kuwait", "bahrain", "oman", "qatar"):
        return {
            "country":  country,
            "is_hague": False,
            "stages": [
                "Certified English translation (if not in Arabic)",
                f"MFA {country} attestation",
                f"UAE Embassy {country} legalisation",
                "UAE MOFA counter-attestation in UAE",
            ],
            "notes": "GCC bilateral attestation arrangement may simplify steps — verify per country.",
        }
    # Non-Hague generic.
    return {
        "country":  country,
        "is_hague": False,
        "stages": [
            "Certified English translation",
            f"Notary Public ({country})",
            f"MFA {country} attestation",
            f"UAE Embassy {country} legalisation",
            "UAE MOFA counter-attestation in UAE",
        ],
        "notes": "Non-Hague jurisdiction — full 4-stage chain required.",
    }


def _attestation_complete(att: dict) -> bool:
    s1 = (att.get("stage1_translation") or {}).get("present") is True
    s2_block = att.get("stage2_home_country") or {}
    # Stage 2 satisfied if apostille=true OR (notary=true AND mfa=true).
    s2 = s2_block.get("apostille") is True or (
        s2_block.get("notary") is True and s2_block.get("mfa") is True
    )
    s3 = (att.get("stage3_uae_embassy") or {}).get("present") is True
    s4 = (att.get("stage4_uae_mofa") or {}).get("present") is True
    return s1 and s2 and s3 and s4


def _corporate_kyc(extracted: dict, shareholders: list[dict]) -> list[dict]:
    # Collect provided corporate docs once; without per-entity tagging in the
    # extractor, attribute the same provided pack to every corporate shareholder.
    provided_labels: list[str] = []
    attestation_blocks: list[dict] = []
    for key, label in _CORPORATE_DOC_LABELS.items():
        node = extracted.get(key)
        if isinstance(node, dict) and node and not node.get("error"):
            provided_labels.append(label)
            att = node.get("attestation")
            if isinstance(att, dict):
                attestation_blocks.append(att)

    # Local Board Resolution (already a top-level doc) covers the
    # "Board Resolution authorising the UAE investment" item when present.
    br = extracted.get("board_resolution") or {}
    if isinstance(br, dict) and br and not br.get("error"):
        provided_labels.append("Board Resolution authorising the UAE investment")

    if attestation_blocks:
        attestation = _merge_attestation(attestation_blocks)
    else:
        attestation = {
            "stage1_translation":  {"present": None},
            "stage2_home_country": {"notary": None, "mfa": None, "apostille": None},
            "stage3_uae_embassy":  {"present": None},
            "stage4_uae_mofa":     {"present": None},
        }
    if _attestation_complete(attestation):
        provided_labels.append("Attested corporate KYC pack (4-stage chain)")

    out: list[dict] = []
    for sh in shareholders:
        if sh.get("type") != "corporate":
            continue
        pct = _share_pct_to_float(sh.get("share_pct", ""))
        required = _CORPORATE_DOCS_100 if (pct is not None and pct >= 99.99) else _CORPORATE_DOCS_PARTNER

        provided = [d for d in required if d in provided_labels]
        out.append({
            "entity":            sh["name"],
            "share_pct":         sh.get("share_pct", ""),
            "jurisdiction":      sh.get("jurisdiction"),
            "required_docs":     required,
            "provided":          provided,
            "missing":           [d for d in required if d not in provided],
            "attestation":       attestation,
            "attestation_path":  _attestation_path_for(sh.get("jurisdiction")),
        })
    return out


# ── Step 8: A-G checklist ────────────────────────────────────────────────────

def _ck(label: str, status: str, detail: str = "") -> dict:
    return {"label": label, "status": status, "detail": detail}


def _build_checklist(extracted: dict, validity: dict, moa_auth: dict,
                     presence: list[dict], shareholders: list[dict],
                     corporate_kyc: list[dict],
                     cross: dict) -> dict:
    # A — Company Documents
    a: list[dict] = []
    for key, label in (("trade_license", "Trade Licence"),
                       ("moa", "Memorandum of Association"),
                       ("ejari", "EJARI Tenancy Contract"),
                       ("vat_certificate", "VAT Certificate"),
                       ("insurance", "Insurance"),
                       ("partners_annex", "Partners Annex")):
        node = extracted.get(key) or {}
        if not node or node.get("error"):
            a.append(_ck(label, "fail", "Not provided"))
            continue
        v = validity.get(key)
        if v is None:
            a.append(_ck(label, "pass", "Provided"))
        else:
            status = {"valid": "pass", "ongoing": "pass",
                      "expiring_soon": "warn", "expired": "fail"}[v["status"]]
            detail = f"Expires {v['expiry_date']}" if v.get("expiry_date") else (v.get("note") or "")
            a.append(_ck(label, status, detail))

    # B — Personal Documents
    b: list[dict] = []
    if presence:
        for row in presence:
            person = row["person"]
            for sub_key, lbl in (("eid_status", "Emirates ID"),
                                 ("passport_status", "Passport"),
                                 ("visa_status", "Residence Visa")):
                s = row[sub_key]
                if s == "missing":
                    b.append(_ck(f"{lbl} — {person}", "fail", "Missing"))
                elif s == "expired":
                    b.append(_ck(f"{lbl} — {person}", "fail", "Expired"))
                elif s == "expiring_soon":
                    b.append(_ck(f"{lbl} — {person}", "warn", "Expiring within 30 days"))
                else:
                    b.append(_ck(f"{lbl} — {person}", "pass", "Valid"))
    else:
        b.append(_ck("Personal documents", "na", "No signatories identified"))

    # C — Cross-Verification
    c: list[dict] = []
    for label, key in (("Company Name", "company_name"),
                       ("Address", "addresses"),
                       ("Licence Number", "licence_number"),
                       ("Date of Birth", "dob"),
                       ("Passport Number", "passport_number"),
                       ("Employer", "employer")):
        m = (cross.get(key) or {}).get("match", "—")
        if m == "✓":
            c.append(_ck(label, "pass", "Match"))
        elif m == "⚠":
            c.append(_ck(label, "warn", "Mismatch"))
        else:
            c.append(_ck(label, "na", "Not enough data to compare"))
    # Person names
    for row in cross.get("person_names", []) or []:
        m = row.get("match", "—")
        label = f"Person: {row.get('name')}"
        if m == "✓":
            c.append(_ck(label, "pass", "Match across docs"))
        elif m == "⚠":
            c.append(_ck(label, "warn", "Name mismatch across docs"))
        else:
            c.append(_ck(label, "na", "Single source"))

    # D — Banking & Authority
    d: list[dict] = []
    if moa_auth["sufficient"]:
        d.append(_ck("MOA banking authority", "pass", moa_auth["reason"]))
    else:
        d.append(_ck("MOA banking authority", "warn", moa_auth["reason"]))
    if moa_auth["resolution_required"]:
        br = extracted.get("board_resolution") or {}
        if br and not br.get("error"):
            d.append(_ck("Board Resolution", "pass", "Provided"))
        else:
            d.append(_ck("Board Resolution", "fail", "Required but not provided"))
    else:
        d.append(_ck("Board Resolution", "na", "Not required (MOA sufficient)"))

    # E — Presence
    e: list[dict] = []
    for row in presence:
        if row["can_proceed"]:
            e.append(_ck(f"Presence — {row['person']}", "pass", "All docs valid, in UAE"))
        else:
            e.append(_ck(f"Presence — {row['person']}", "warn", row["action"]))
    if not presence:
        e.append(_ck("Presence", "na", "No signatories to evaluate"))

    # F — Corporate Shareholders
    f: list[dict] = []
    if corporate_kyc:
        for ck in corporate_kyc:
            missing = ck.get("missing") or []
            if not missing:
                f.append(_ck(f"{ck['entity']} corporate KYC", "pass", "Complete"))
            else:
                f.append(_ck(f"{ck['entity']} corporate KYC", "fail",
                             f"{len(missing)} missing doc(s)"))
    else:
        f.append(_ck("Corporate shareholder KYC", "na",
                     "No corporate shareholders identified"))

    # G — Final Status (placeholder; recomputed after flags)
    g: list[dict] = [_ck("Overall status", "na", "Computed from flags")]

    return {"A": a, "B": b, "C": c, "D": d, "E": e, "F": f, "G": g}


# ── Step 9: flags ────────────────────────────────────────────────────────────

def _flag(code: str, severity: str, kyc_status: str, *,
          documents_affected, field: str, issue: str,
          recommended_action: str) -> dict:
    return {
        "code":               code,
        "severity":           severity,
        "kyc_status":         kyc_status,
        "documents_affected": documents_affected,
        "field":              field,
        "issue":              issue,
        "recommended_action": recommended_action,
    }


def _build_flags(extracted: dict, validity: dict, moa_auth: dict,
                 presence: list[dict], shareholders: list[dict],
                 corporate_kyc: list[dict], cross: dict,
                 poa_status: dict | None = None) -> list[dict]:
    flags: list[dict] = []

    # FLAG_01 — MOA silent on banking authority
    moa = extracted.get("moa") or {}
    if moa and not moa.get("error") and not moa_auth["sufficient"]:
        flags.append(_flag(
            "FLAG_01_BANKING_AUTHORITY_MISSING", "warn", "INCOMPLETE",
            documents_affected=["MOA"], field="Banking Authority",
            issue=moa_auth["reason"],
            recommended_action="Obtain a Board / Owner's Resolution granting explicit banking powers.",
        ))

    # FLAG_02 — Resolution required but missing
    br = extracted.get("board_resolution") or {}
    if moa_auth["resolution_required"] and (not br or br.get("error")):
        flags.append(_flag(
            "FLAG_02_RESOLUTION_MISSING", "error", "ON_HOLD",
            documents_affected=["Board Resolution"], field="Resolution",
            issue="Banking authority not derivable from MOA and no Board Resolution provided.",
            recommended_action="Upload a notarised Board / Owner's Resolution.",
        ))

    # FLAG_03 — Signatory not in UAE
    for row in presence:
        if not row["in_uae"]:
            flags.append(_flag(
                "FLAG_03_SIGNATORY_NOT_IN_UAE", "warn", "ON_HOLD",
                documents_affected=["Residence Visa"],
                field=f"{row['person']} — Residence Visa",
                issue=f"{row['person']} has no valid UAE residence visa "
                      f"({row['visa_status']}).",
                recommended_action="Arrange valid UAE residence or appoint a UAE-resident POA.",
            ))

    # FLAG_04 — Expired personal doc
    for row in presence:
        for status_key, lbl in (("eid_status", "Emirates ID"),
                                ("passport_status", "Passport"),
                                ("visa_status", "Residence Visa")):
            if row[status_key] == "expired":
                flags.append(_flag(
                    "FLAG_04_PERSONAL_DOC_EXPIRED", "error", "BLOCKED",
                    documents_affected=[lbl],
                    field=f"{row['person']} — {lbl}",
                    issue=f"{lbl} for {row['person']} has expired.",
                    recommended_action=f"Renew {lbl} before proceeding.",
                ))
            elif row[status_key] == "expiring_soon":
                flags.append(_flag(
                    "FLAG_04_PERSONAL_DOC_EXPIRED", "warn", "INCOMPLETE",
                    documents_affected=[lbl],
                    field=f"{row['person']} — {lbl}",
                    issue=f"{lbl} for {row['person']} expires within 30 days.",
                    recommended_action=f"Initiate {lbl} renewal.",
                ))

    # FLAG_05 — POA grantee unverified / POA notarisation incomplete
    poa = extracted.get("poa") or {}
    if poa and not poa.get("error") and poa.get("grantee_name"):
        grantee = _s(poa["grantee_name"])
        docs = _find_personal_docs(extracted, grantee)
        if not (docs["passport"] or docs["emirates_id"]):
            flags.append(_flag(
                "FLAG_05_POA_GRANTEE_UNVERIFIED", "error", "ON_HOLD",
                documents_affected=["POA"], field=f"POA grantee — {grantee}",
                issue="POA grantee provided but no matching ID/passport on file.",
                recommended_action="Upload grantee's Passport, Emirates ID, and Visa.",
            ))

        # POA notarisation gate (spec 6B).
        # If signed in UAE → require Notary Public stamp.
        # If signed abroad → require UAE Embassy + UAE MOFA in addition.
        notar = poa.get("notarisation") or {}
        notary_pub  = notar.get("notary_public") if isinstance(notar, dict) else None
        uae_embassy = notar.get("uae_embassy")   if isinstance(notar, dict) else None
        mofa        = notar.get("mofa")          if isinstance(notar, dict) else None
        signed_country = _s(poa.get("signed_in_country") or "").lower()
        signed_abroad  = bool(poa.get("signed_abroad")) or (
            bool(signed_country) and "united arab emirates" not in signed_country
            and "uae" not in signed_country
        )
        # Fall back to the legacy `notarised` boolean if structured block is absent.
        legacy_notarised = poa.get("notarised")
        if notary_pub is None and isinstance(legacy_notarised, bool):
            notary_pub = legacy_notarised

        missing_stages: list[str] = []
        if notary_pub is False or notary_pub is None:
            missing_stages.append("Notary Public")
        if signed_abroad:
            if uae_embassy is False or uae_embassy is None:
                missing_stages.append("UAE Embassy attestation")
            if mofa is False or mofa is None:
                missing_stages.append("UAE MOFA counter-attestation")

        if missing_stages:
            flags.append(_flag(
                "FLAG_05B_POA_NOTARISATION_INCOMPLETE", "error", "ON_HOLD",
                documents_affected=["POA"], field=f"POA — {grantee}",
                issue=("POA notarisation/attestation incomplete: "
                       f"{', '.join(missing_stages)}."),
                recommended_action=(
                    "POA signed in UAE must be notarised by a UAE Notary Public. "
                    "POA signed abroad must additionally carry UAE Embassy attestation "
                    "and UAE MOFA counter-attestation before it can be relied upon for "
                    "bank account opening."
                ),
            ))

    # FLAG_05C — POA grantee not eligible (spec 6C: must be UAE resident,
    # ≥21 years old, not the company auditor).
    if poa_status and poa_status.get("present") and poa_status.get("grantee"):
        elig = poa_status.get("grantee_eligibility") or {}
        reasons: list[str] = []
        if elig.get("uae_resident") is False:
            reasons.append("not a UAE resident (no valid Residence Visa)")
        if elig.get("eid_valid") is False:
            reasons.append("Emirates ID not valid")
        if elig.get("passport_valid") is False:
            reasons.append("Passport not valid")
        if elig.get("age_at_least_21") is False:
            reasons.append("under 21 years of age")
        if elig.get("not_auditor") is False:
            reasons.append("conflicted (acts as auditor)")
        if reasons and not elig.get("eligible"):
            flags.append(_flag(
                "FLAG_05C_POA_GRANTEE_INELIGIBLE", "error", "ON_HOLD",
                documents_affected=["POA"],
                field=f"POA grantee — {poa_status['grantee']}",
                issue=("POA grantee fails spec 6C eligibility: "
                       f"{'; '.join(reasons)}."),
                recommended_action=(
                    "Appoint a UAE-resident attorney aged 21+ with valid EID, Passport, "
                    "and Residence Visa, and no conflict of interest with the company."
                ),
            ))

    # FLAG_06 — VAT registered address ≠ Trade Licence address (per spec).
    # FTA-update language is specific. Emit a separate row when TL vs VAT mismatch,
    # and a generic mismatch row for any other variance (TL vs EJARI etc.).
    tl = extracted.get("trade_license") or {}
    vat = extracted.get("vat_certificate") or {}
    tl_addr = _s(tl.get("registered_address"))
    vat_addr = _s(vat.get("registered_address"))
    if tl_addr and vat_addr and not _equal_norm(tl_addr, vat_addr):
        flags.append(_flag(
            "FLAG_06_VAT_ADDRESS_MISMATCH", "warn", "COMPLIANCE_GAP",
            documents_affected=["Trade Licence", "VAT Certificate"],
            field="Registered Address",
            issue=f"VAT registered address ({vat_addr}) differs from Trade Licence "
                  f"address ({tl_addr}).",
            recommended_action="Client must update the registered address with the "
                               "Federal Tax Authority via the EmaraTax portal so it matches "
                               "the current Trade Licence address. UAE VAT compliance "
                               "requirement — does not block KYC.",
        ))
    elif (cross.get("addresses") or {}).get("match") == "⚠":
        flags.append(_flag(
            "FLAG_06_ADDRESS_MISMATCH", "warn", "COMPLIANCE_GAP",
            documents_affected=["Trade Licence", "EJARI", "VAT"],
            field="Registered Address",
            issue="Address differs across Trade Licence / EJARI / VAT.",
            recommended_action="Align addresses or document the variance.",
        ))

    # FLAG_07 — Name mismatch (company or person)
    if (cross.get("company_name") or {}).get("match") == "⚠":
        flags.append(_flag(
            "FLAG_07_NAME_MISMATCH", "warn", "COMPLIANCE_GAP",
            documents_affected=["Trade Licence", "MOA", "VAT"],
            field="Company Name",
            issue="Company name differs across documents.",
            recommended_action="Reconcile company name across all corporate filings.",
        ))
    for row in cross.get("person_names", []) or []:
        if row.get("match") == "⚠":
            flags.append(_flag(
                "FLAG_07_NAME_MISMATCH", "warn", "COMPLIANCE_GAP",
                documents_affected=["EID", "Passport", "Visa", "BR"],
                field=f"Person — {row['name']}",
                issue=f"Name spelling differs across documents for {row['name']}.",
                recommended_action="Confirm correct legal name spelling and update where wrong.",
            ))

    # FLAG_08 — Missing personal doc for an expected signatory/partner
    expected_people: list[str] = []
    for sh in shareholders:
        if sh["type"] == "natural" and sh["name"]:
            expected_people.append(sh["name"])
    for row in presence:
        expected_people.append(row["person"])
    seen_e: set[str] = set()
    for name in expected_people:
        key = _norm(name)
        if not key or key in seen_e:
            continue
        seen_e.add(key)
        docs = _find_personal_docs(extracted, name)
        missing_subs = [lbl for sub_key, lbl in (
            ("emirates_id", "Emirates ID"),
            ("passport", "Passport"),
            ("residence_visa", "Residence Visa")) if not docs[sub_key]]
        if missing_subs:
            flags.append(_flag(
                "FLAG_08_PERSONAL_DOC_MISSING", "warn", "INCOMPLETE",
                documents_affected=missing_subs, field=name,
                issue=f"No {', '.join(missing_subs)} on file for {name}.",
                recommended_action=f"Upload {', '.join(missing_subs)} for {name}.",
            ))

    # FLAG_09 — Corporate shareholder docs missing
    for ck in corporate_kyc:
        if ck["missing"]:
            flags.append(_flag(
                "FLAG_09_CORPORATE_DOCS_MISSING", "error", "ON_HOLD",
                documents_affected=ck["missing"],
                field=f"Corporate KYC — {ck['entity']}",
                issue=f"{len(ck['missing'])} corporate document(s) missing for {ck['entity']}.",
                recommended_action="Provide the listed corporate KYC documents, attested.",
            ))

    # FLAG_10 — Attestation chain incomplete
    for ck in corporate_kyc:
        att = ck.get("attestation") or {}
        # Mark as flag whenever any stage is False (not None=unknown).
        bad_stages = []
        for stage_key in ("stage1_translation", "stage2_home_country",
                          "stage3_uae_embassy", "stage4_uae_mofa"):
            stage = att.get(stage_key) or {}
            for v in stage.values():
                if v is False:
                    bad_stages.append(stage_key)
                    break
        if bad_stages:
            flags.append(_flag(
                "FLAG_10_ATTESTATION_INCOMPLETE", "error", "BLOCKED",
                documents_affected=["Attestation chain"],
                field=f"Corporate KYC — {ck['entity']}",
                issue=f"Attestation chain incomplete: {', '.join(bad_stages)}.",
                recommended_action="Complete the 4-stage attestation chain "
                                   "(translation → home MFA / apostille → UAE embassy → MOFA).",
            ))

    # FLAG_11 — Translation missing (Phase 2 fills attestation; warn until then)
    for ck in corporate_kyc:
        att = ck.get("attestation") or {}
        s1 = att.get("stage1_translation") or {}
        if s1.get("present") is False:
            flags.append(_flag(
                "FLAG_11_TRANSLATION_MISSING", "warn", "INCOMPLETE",
                documents_affected=["Translation"],
                field=f"Corporate KYC — {ck['entity']}",
                issue="Certified translation to English/Arabic not provided.",
                recommended_action="Procure a certified legal translation.",
            ))

    # FLAG_12 — Corporate partner board resolution missing
    for sh in shareholders:
        if sh["type"] != "corporate":
            continue
        # If we have a corporate partner, a Board Resolution from THAT entity
        # authorising the UAE investment is required (separate from local BR).
        # We can't yet detect this resolution per-entity until Phase 2.
        # Heuristic: emit if no overall board_resolution is present.
        if not br or br.get("error"):
            flags.append(_flag(
                "FLAG_12_CORPORATE_PARTNER_BR_MISSING", "warn", "INCOMPLETE",
                documents_affected=["Board Resolution"],
                field=f"Corporate Partner — {sh['name']}",
                issue=f"No Board Resolution from {sh['name']} authorising the UAE investment.",
                recommended_action="Obtain corporate-partner Board Resolution authorising the UAE entity.",
            ))

    return flags


# ── Step 10: versioning ──────────────────────────────────────────────────────

def _has_doc(extracted: dict, key: str) -> bool:
    node = extracted.get(key)
    return isinstance(node, dict) and bool(node) and not node.get("error")


def _has_personal(extracted: dict) -> bool:
    if any(_has_doc(extracted, k) for k in ("emirates_id", "passport", "residence_visa")):
        return True
    pdocs = extracted.get("partner_personal_docs") or []
    if isinstance(pdocs, list):
        for entry in pdocs:
            if not isinstance(entry, dict):
                continue
            for k in ("emirates_id", "passport", "residence_visa"):
                d = entry.get(k)
                if isinstance(d, dict) and not d.get("error"):
                    return True
    return False


def _has_corporate_shareholder_docs(extracted: dict) -> bool:
    for k in ("certificate_of_incorporation", "register_of_shareholders",
              "register_of_directors", "certificate_of_good_standing"):
        if _has_doc(extracted, k):
            return True
    return False


def _compute_version(extracted: dict) -> str:
    has_tl   = _has_doc(extracted, "trade_license")
    has_moa  = _has_doc(extracted, "moa")
    has_ej   = _has_doc(extracted, "ejari")
    has_pers = _has_personal(extracted)
    has_vat  = _has_doc(extracted, "vat_certificate")
    has_brpoa = _has_doc(extracted, "board_resolution") or _has_doc(extracted, "poa")
    has_corp = _has_corporate_shareholder_docs(extracted)

    if has_tl and has_moa and has_ej and has_pers and has_vat and has_brpoa and has_corp:
        return "v7"
    if has_tl and has_moa and has_ej and has_pers and has_vat and has_brpoa:
        return "v6"
    if has_tl and has_moa and has_ej and has_pers and has_vat:
        return "v5"
    if has_tl and has_moa and has_ej and has_pers:
        return "v4"
    if has_tl and has_moa and has_ej:
        return "v3"
    if has_tl and has_moa:
        return "v2"
    if has_tl:
        return "v1"
    return "v0"


# ── Public entry point ───────────────────────────────────────────────────────

def analyse(extracted: dict, today: date) -> dict:
    """Compute the full compliance / analysis dict for a KYC submission.

    `extracted` is the per-doc-type dict produced by the extractor (each value
    either a dict of fields or `{"error": "..."}`). May also contain
    `partner_personal_docs` for the multi-partner flow.
    """
    if not isinstance(extracted, dict):
        extracted = {}

    validity      = _compute_validity(extracted, today)
    cross         = _cross_check(extracted)
    moa_auth      = _assess_moa_authority(extracted)
    presence      = _check_presence(extracted, today, moa_auth)
    shareholders  = _classify_shareholders(extracted)
    corporate_kyc = _corporate_kyc(extracted, shareholders)
    poa_status    = _assess_poa(extracted, today)
    flags         = _build_flags(extracted, validity, moa_auth, presence,
                                 shareholders, corporate_kyc, cross,
                                 poa_status=poa_status)
    checklist     = _build_checklist(extracted, validity, moa_auth, presence,
                                     shareholders, corporate_kyc, cross)
    version       = _compute_version(extracted)

    return {
        "validity":      validity,
        "cross_checks":  cross,
        "moa_authority": moa_auth,
        "presence":      presence,
        "shareholders":  shareholders,
        "corporate_kyc": corporate_kyc,
        "poa":           poa_status,
        "checklist":     checklist,
        "flags":         flags,
        "version":       version,
    }


# ── POA assessment ──────────────────────────────────────────────────────────

# Spec 6C — POA grantee eligibility.
# Auditor-conflict words that disqualify a grantee.
_AUDITOR_HINTS = ("auditor", "audit firm", "external auditor", "chartered accountant")


def _assess_poa(extracted: dict, today: date) -> dict:
    poa = extracted.get("poa") or {}
    if not poa or poa.get("error"):
        return {"present": False}

    grantee_name = _s(poa.get("grantee_name") or poa.get("grantee"))
    grantor_name = _s(poa.get("grantor_name") or poa.get("grantor"))

    # Validity (prefer structured validity_until, fall back to expiry_date).
    val = _validity_for(poa.get("expiry_date") or poa.get("validity_until"), today)
    valid_window = val["status"] in ("valid", "expiring_soon") if val else None

    # Notarisation breakdown.
    notar = poa.get("notarisation") if isinstance(poa.get("notarisation"), dict) else {}
    signed_country = _s(poa.get("signed_in_country") or "").lower()
    signed_abroad = bool(poa.get("signed_abroad")) or (
        bool(signed_country) and "united arab emirates" not in signed_country
        and "uae" not in signed_country
    )
    notary_pub  = notar.get("notary_public")
    uae_embassy = notar.get("uae_embassy")
    mofa        = notar.get("mofa")
    if notary_pub is None and isinstance(poa.get("notarised"), bool):
        notary_pub = poa["notarised"]

    if signed_abroad:
        notar_complete = bool(notary_pub) and bool(uae_embassy) and bool(mofa)
    else:
        notar_complete = bool(notary_pub)

    # Grantee eligibility (spec 6C).
    docs = _find_personal_docs(extracted, grantee_name) if grantee_name else {
        "emirates_id": None, "passport": None, "residence_visa": None,
    }
    eid_valid  = docs["emirates_id"]   and _doc_validity_status(docs["emirates_id"], today)   == "valid"
    pp_valid   = docs["passport"]      and _doc_validity_status(docs["passport"], today)      == "valid"
    visa_valid = docs["residence_visa"] and _doc_validity_status(docs["residence_visa"], today) == "valid"
    has_uae_residency = bool(visa_valid) or poa.get("grantee_uae_resident") is True

    # Age check — needs DOB on grantee record (Passport, EID, or POA itself).
    age_ok: bool | None = None
    for source in (
        (docs.get("passport") or {}).get("date_of_birth"),
        (docs.get("emirates_id") or {}).get("date_of_birth"),
        poa.get("grantee_date_of_birth"),
    ):
        d = _parse_date(source)
        if d:
            age = (today - d).days // 365
            age_ok = age >= 21
            break

    # Auditor / conflict-of-interest hint.
    profession = " ".join([
        _s((docs.get("emirates_id") or {}).get("occupation")),
        _s((docs.get("residence_visa") or {}).get("profession")),
        _s(poa.get("grantee_designation")),
    ]).lower()
    not_auditor: bool | None = None
    if profession.strip():
        not_auditor = not any(h in profession for h in _AUDITOR_HINTS)

    eligible = bool(
        grantee_name
        and eid_valid and pp_valid and visa_valid
        and has_uae_residency
        and (age_ok is True or age_ok is None)
        and (not_auditor is True or not_auditor is None)
    )

    return {
        "present":            True,
        "grantor":            grantor_name or None,
        "grantee":            grantee_name or None,
        "validity":           val,
        "within_validity":    valid_window,
        "signed_abroad":      signed_abroad,
        "signed_in_country":  poa.get("signed_in_country"),
        "notarisation": {
            "notary_public": bool(notary_pub) if notary_pub is not None else None,
            "uae_embassy":   bool(uae_embassy) if uae_embassy is not None else None,
            "mofa":          bool(mofa) if mofa is not None else None,
            "complete":      notar_complete,
        },
        "grantee_eligibility": {
            "eid_valid":          bool(eid_valid),
            "passport_valid":     bool(pp_valid),
            "visa_valid":         bool(visa_valid),
            "uae_resident":       has_uae_residency,
            "age_at_least_21":    age_ok,
            "not_auditor":        not_auditor,
            "eligible":           eligible,
        },
        "usable":             bool(notar_complete and eligible and (valid_window is not False)),
    }
