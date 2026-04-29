"""
Name reconciliation across extracted KYC documents.

Problem: MOAs / Trade Licences / Partners Annex extractions transliterate
Arabic-primary partner names into English, and the transliteration drifts
(رضوان → "Radwan" / "Rizwan" / "Rezwan"). The passport / Emirates ID hold
the authoritative English spelling.

Strategy: build an index of (Arabic tokens, English tokens, ID digits, English
name) from passport / EID / visa documents (top-level AND per-partner
entries). For every partner-shaped field elsewhere, look up the canonical
English name by trying these match keys in order of confidence:

  1. Emirates-ID number (digits-only). MOAs print "بطاقة هوية رقم 784..."
     next to each party — exact ID match is the gold standard.
  2. Arabic token overlap (≥2 tokens, or full coverage of one side).
  3. English token overlap (≥2 matching tokens, ≥50 % min-side coverage).
     Catches "Radwan Ahmed Mohammed Abdul Rahim" ↔
     "REZWAN AHMED MOHAMMED ABDUL RAHIM" — 4-of-5 tokens identical even
     though the first token disagrees.
"""

import re
import unicodedata


def _normalize_arabic(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.category(c).startswith("M"))
    for alef in "إأآٱ":
        s = s.replace(alef, "ا")
    s = (s.replace("ى", "ي")
           .replace("ة", "ه")
           .replace("ؤ", "و")
           .replace("ئ", "ي"))
    return " ".join(s.split())


def _arabic_tokens(s: str | None) -> set[str]:
    return {t for t in _normalize_arabic(s).split() if len(t) > 1}


def _english_tokens(s: str | None) -> set[str]:
    if not s:
        return set()
    cleaned = re.sub(r"[^A-Za-z\s]", " ", str(s)).upper()
    return {t for t in cleaned.split() if len(t) > 1}


def _digits_only(s) -> str:
    return "".join(c for c in str(s or "") if c.isdigit())


def _build_canonical_index(extracted: dict) -> list[dict]:
    """Walk every authoritative source and emit one index entry per person."""
    index: list[dict] = []

    def _add(d):
        if isinstance(d, list):
            for item in d:
                _add(item)
            return
        if not isinstance(d, dict):
            return
        en = (d.get("holder_name") or "").strip()
        if not en:
            return
        ar = d.get("holder_name_arabic")
        idn = d.get("id_number") or d.get("uid_number") or ""
        index.append({
            "ar_tokens": _arabic_tokens(ar),
            "en_tokens": _english_tokens(en),
            "id_digits": _digits_only(idn),
            "english_name": en,
        })

    for src in ("passport", "emirates_id", "residence_visa"):
        _add(extracted.get(src))
    for pdoc in extracted.get("partner_personal_docs") or []:
        if isinstance(pdoc, dict):
            for src in ("passport", "emirates_id", "residence_visa"):
                _add(pdoc.get(src))
    return index


def _lookup_canonical(arabic, english, id_number, index: list[dict]) -> str | None:
    if not index:
        return None

    target_id = _digits_only(id_number)
    target_ar = _arabic_tokens(arabic)
    target_en = _english_tokens(english)

    # 1. ID-number exact match (highest confidence)
    if target_id and len(target_id) >= 10:
        for entry in index:
            if entry["id_digits"] and entry["id_digits"] == target_id:
                return entry["english_name"]

    # 2. Arabic token overlap
    if target_ar:
        best, best_score = None, 0.0
        for entry in index:
            ar = entry["ar_tokens"]
            if not ar:
                continue
            overlap = len(target_ar & ar)
            if overlap == 0:
                continue
            coverage = overlap / len(ar)
            if (overlap >= 2 or coverage >= 1.0) and coverage > best_score:
                best_score = coverage
                best = entry["english_name"]
        if best and best_score >= 0.5:
            return best

    # 3. English token overlap (handles transliteration drift)
    if len(target_en) >= 2:
        best, best_score = None, 0.0
        for entry in index:
            en = entry["en_tokens"]
            if not en:
                continue
            overlap = len(target_en & en)
            if overlap < 2:
                continue
            min_len = min(len(target_en), len(en))
            coverage = overlap / min_len if min_len else 0.0
            if coverage >= 0.5 and coverage > best_score:
                best_score = coverage
                best = entry["english_name"]
        if best:
            return best

    return None


def reconcile_names(extracted: dict) -> dict:
    """Override transliterated English names everywhere using canonical
    spellings from passport / EID / visa. Mutates and returns extracted."""
    index = _build_canonical_index(extracted)
    if not index:
        return extracted

    moa = extracted.get("moa")
    if isinstance(moa, dict) and not moa.get("error"):
        for sh in moa.get("shareholders") or []:
            if isinstance(sh, dict):
                m = _lookup_canonical(
                    sh.get("name_arabic"),
                    sh.get("name"),
                    sh.get("person_number"),
                    index,
                )
                if m:
                    sh["name"] = m
        for mgr in moa.get("managers") or []:
            if isinstance(mgr, dict):
                m = _lookup_canonical(
                    mgr.get("name_arabic"),
                    mgr.get("name"),
                    mgr.get("person_number"),
                    index,
                )
                if m:
                    mgr["name"] = m
        for en_key, ar_key, id_key in (
            ("owner_name", "owner_name_arabic", "owner_person_number"),
            ("manager_name", "manager_name_arabic", "manager_person_number"),
        ):
            m = _lookup_canonical(
                moa.get(ar_key), moa.get(en_key), moa.get(id_key), index,
            )
            if m:
                moa[en_key] = m

    pa = extracted.get("partners_annex")
    if isinstance(pa, dict) and not pa.get("error"):
        for p in pa.get("partners") or []:
            if isinstance(p, dict):
                m = _lookup_canonical(
                    p.get("name_arabic"),
                    p.get("name"),
                    p.get("person_number"),
                    index,
                )
                if m:
                    p["name"] = m

    tl = extracted.get("trade_license")
    if isinstance(tl, dict) and not tl.get("error"):
        for en_key, ar_key, id_key in (
            ("owner_name", "owner_name_arabic", "owner_person_number"),
            ("manager_name", "manager_name_arabic", "manager_person_number"),
        ):
            m = _lookup_canonical(
                tl.get(ar_key), tl.get(en_key), tl.get(id_key), index,
            )
            if m:
                tl[en_key] = m

    ej = extracted.get("ejari")
    if isinstance(ej, dict) and not ej.get("error"):
        for en_key, ar_key in (
            ("tenant_name", "tenant_name_arabic"),
            ("landlord_name", "landlord_name_arabic"),
        ):
            m = _lookup_canonical(
                ej.get(ar_key), ej.get(en_key), None, index,
            )
            if m:
                ej[en_key] = m

    # Sync partner_personal_docs.partner_name with embedded passport/EID/visa
    # so multi-partner reports display canonical names.
    ppd = extracted.get("partner_personal_docs")
    if isinstance(ppd, list):
        for entry in ppd:
            if not isinstance(entry, dict):
                continue
            for src_key in ("passport", "emirates_id", "residence_visa"):
                src = entry.get(src_key)
                if isinstance(src, dict) and src.get("holder_name"):
                    entry["partner_name"] = src["holder_name"]
                    break

    return extracted
