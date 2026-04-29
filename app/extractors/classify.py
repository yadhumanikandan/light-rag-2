"""Single-document classifier (gpt-5 vision, page-1, low detail) for the bulk-upload UI."""
import json

from app.extractors._clients import openai, OCR_MODEL
from app.extractors._images import first_page_image
from app.extractors._ocr import strip_json_fences

CLASSIFY_TYPES = {
    "passport", "emirates_id", "residence_visa", "trade_license", "ejari",
    "moa", "insurance", "vat_certificate", "board_resolution", "poa",
    "partners_annex", "certificate_of_incorporation", "register_of_shareholders",
    "register_of_directors", "certificate_of_good_standing",
    "free_zone_license", "dcci_membership", "renewal_receipt",
    "audited_financials", "ubo_declaration", "specimen_signatures",
    "unknown",
}

CLASSIFY_SYSTEM = (
    "You are a UAE KYC document classifier. Identify the document type from its header, "
    "issuing-authority logo/seal, layout and key phrases. Return ONLY a JSON object:\n"
    '{"doc_type": "<allowed value>", "confidence": "high|medium|low", "reason": "<≤15 words, cite the visible cue>"}\n\n'
    "ALLOWED VALUES with discriminating cues (English + common Arabic header):\n"
    "- passport — passport booklet page; MRZ at bottom (P< / two-line `<<<`); 'PASSPORT / جواز سفر'; "
    "any country (UAE, India, Pakistan, Bangladesh, UK, etc.). NOT a visa sticker.\n"
    "- emirates_id — UAE Emirates ID card (polycarbonate). Front: photo + 'United Arab Emirates / "
    "الهوية' + 784-XXXX-XXXXXXX-X. Back: card-holder signature + occupation + chip; treat front AND "
    "back BOTH as emirates_id.\n"
    "- residence_visa — visa sticker INSIDE a passport page or e-visa PDF; 'Residence / إقامة', "
    "'U.I.D. No', 'Visa File No', sponsor name. NOT the EID card.\n"
    "- trade_license — UAE mainland trade licence: 'Trade Licence / الرخصة التجارية' issued by DED "
    "(Department of Economic Development / Economic Department) of an emirate. Has Licence No., "
    "legal form, partners list. NOT a free-zone authority.\n"
    "- free_zone_license — UAE free-zone licence: header names a free-zone authority — DMCC, IFZA, "
    "RAKEZ, RAK ICC, JAFZA, DAFZA, ADGM, DIFC, SHAMS, Meydan, UAQ FTZ, Dubai South, KIZAD, "
    "Fujairah Creative City, twofour54, Masdar. NOT DED.\n"
    "- ejari — Dubai Ejari tenancy contract (RERA-registered). Header 'Ejari / إيجاري' or 'Tenancy "
    "Contract' with Ejari contract number / Dubai Land Department / RERA logo. Tawtheeq (Abu Dhabi) "
    "and other emirate tenancy contracts also map here.\n"
    "- moa — Memorandum / Articles of Association. Long contract document, 'Memorandum of "
    "Association / عقد التأسيس', clauses about capital, share split, partners, manager. "
    "Bilingual columns common. NOT a one-page resolution.\n"
    "- board_resolution — short 'Resolution' document: 'Board Resolution', 'Shareholders' Resolution', "
    "'RESOLVED THAT…' clauses. Authorises a specific act (open bank account, appoint signatory). "
    "Usually 1-3 pages. NOT a full MOA.\n"
    "- poa — 'Power of Attorney / توكيل'. Grantor appoints a named attorney-in-fact. Often "
    "notarised by UAE notary public or foreign notary + embassy. NOT a board resolution.\n"
    "- partners_annex — Partners' Annex / Shareholders Appendix attached to the MOA, listing "
    "partners with shares. Header often 'Annex' or 'ملحق الشركاء'.\n"
    "- insurance — insurance policy / certificate; insurer logo (Oman Insurance, AXA, Orient, etc.); "
    "'Policy No.', 'Sum Insured', cover period.\n"
    "- vat_certificate — single-page UAE VAT registration certificate from Federal Tax Authority "
    "(FTA / الهيئة الاتحادية للضرائب). Shows TRN (15-digit) + effective date. NOT a tax invoice.\n"
    "- certificate_of_incorporation — Certificate of Incorporation issued at company formation by a "
    "registrar (Companies House UK, ADGM Registrar, BVI FSC, etc.). States the company is duly "
    "incorporated. One-page.\n"
    "- certificate_of_good_standing — Certificate of Good Standing / Incumbency / Continued "
    "Existence. Issued AFTER incorporation to confirm current active status. NOT the incorporation "
    "certificate.\n"
    "- register_of_shareholders — formal Register of Shareholders / Members maintained by company "
    "secretary; columnar table of shareholders, share class, count, dates of allotment/transfer.\n"
    "- register_of_directors — Register of Directors / Officers; columnar table of directors with "
    "appointment / resignation dates.\n"
    "- dcci_membership — Dubai Chamber of Commerce & Industry membership certificate ONLY. "
    "Specifically the DCCI logo + 'Member of Dubai Chamber'.\n"
    "- renewal_receipt — trade-licence renewal RECEIPT / payment voucher / fee invoice. Short, "
    "shows fees paid + receipt number. NOT the licence itself.\n"
    "- audited_financials — Audited Financial Statements / Auditor's Report. Multi-page; auditor's "
    "opinion + Balance Sheet + Profit & Loss + signature of audit firm.\n"
    "- ubo_declaration — Ultimate Beneficial Owner declaration / Real-Beneficiary register / "
    "'UBO Form'. Lists natural persons owning ≥25%.\n"
    "- specimen_signatures — Specimen Signatures certificate / signature card; sample signatures of "
    "authorised signatories, often attested.\n"
    "- unknown — only if no discriminator above is visible.\n\n"
    "DISAMBIGUATION RULES (apply in order):\n"
    "1. If the issuer is a UAE free-zone authority → free_zone_license, NEVER trade_license.\n"
    "2. If the page is a visa sticker inside a passport booklet → residence_visa, NOT passport.\n"
    "3. The back of an Emirates ID card → emirates_id (same type as the front).\n"
    "4. 'Memorandum of Association' (multi-clause contract) → moa; one-page 'Resolution' → "
    "board_resolution; 'Power of Attorney' → poa — these are NOT interchangeable.\n"
    "5. 'Certificate of Incorporation' (formed-on date) ≠ 'Good Standing' (currently-active).\n"
    "6. Tenancy contract from any emirate → ejari (Dubai Ejari is the canonical case).\n\n"
    "CONFIDENCE:\n"
    "- high  — issuer logo / mandatory header phrase clearly visible.\n"
    "- medium — layout matches but logo/header partially visible.\n"
    "- low   — guessing from weak cues.\n\n"
    "Output: ONLY the JSON object, no markdown fences, no commentary."
)


async def classify_document(file_bytes: bytes, filename: str) -> dict:
    """Classify a single document into one of the supported KYC doc types."""
    try:
        img = first_page_image(file_bytes, filename)
    except Exception as exc:
        return {"doc_type": "unknown", "confidence": "low", "reason": f"read error: {exc}"}
    if img is None:
        return {"doc_type": "unknown", "confidence": "low", "reason": "empty file"}

    b64, media_type = img
    try:
        resp = await openai.chat.completions.create(
            model=OCR_MODEL,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "low"}},
                    {"type": "text", "text": "Classify this document. Return JSON only."},
                ]},
            ],
            reasoning_effort="minimal",
            max_completion_tokens=120,
            response_format={"type": "json_object"},
        )
        text = strip_json_fences((resp.choices[0].message.content or "").strip())
        result = json.loads(text)
        dt = result.get("doc_type", "unknown")
        if dt not in CLASSIFY_TYPES:
            dt = "unknown"
        conf = result.get("confidence", "medium")
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        return {
            "doc_type": dt,
            "confidence": conf,
            "reason": (result.get("reason") or "")[:160],
        }
    except json.JSONDecodeError:
        return {"doc_type": "unknown", "confidence": "low", "reason": "parse error"}
    except Exception as exc:
        return {"doc_type": "unknown", "confidence": "low", "reason": f"classify error: {exc}"}
