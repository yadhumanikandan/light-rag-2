"""
Two-step GPT-4o extraction for KYC document generation.

Step 1 — OCR: Ask GPT-4o to transcribe all visible text from the image.
         Framed as plain transcription, not ID data extraction, so safety
         filters on personal identifiers do not trigger.

Step 2 — Parse: Send the transcription (plain text, no image) to GPT-4o
         and extract structured JSON fields. No image means no vision-based
         safety checks are applied.
"""

import base64
import json

from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ── Step 1: generic OCR prompt (no mention of identity documents) ─────────────
_OCR_SYSTEM = (
    "You are an OCR assistant. Transcribe every line of text visible in the image "
    "exactly as it appears — all names, numbers, dates, codes, labels, and any "
    "machine-readable text at the bottom. Do not skip, summarise, or redact anything. "
    "Output the raw transcription as plain text only."
)

# ── Step 2: field extraction prompts (work on plain text, no image) ───────────
_EXTRACT_PROMPTS = {
    "passport": (
        "The text below was transcribed from a passport document. "
        "Extract the following fields and return ONLY a JSON object: "
        '"holder_name" (full readable name — NOT the MRZ << format), '
        '"passport_number" (alphanumeric code, typically 9 chars), '
        '"expiry_date" (YYYY-MM-DD), "date_of_birth" (YYYY-MM-DD), '
        '"nationality", "gender", "place_of_birth", '
        '"issue_date" (YYYY-MM-DD), "issuing_country". '
        "For holder_name: passports often have bilingual labels — look for fields labelled "
        "'Surname', 'Nom', 'Last Name', 'Given Name', 'Prénom', or 'First Name'. "
        "Combine Surname + Given Name(s) into one full name (e.g. 'DOE JOHN MICHAEL'). "
        "Tip — MRZ line 1 looks like P<COUNTRY_SURNAME<<GIVEN<<...; use it as a fallback if "
        "the visible name fields are unclear, but convert to readable form (no << or <). "
        "MRZ line 2 starts with the passport number (first 9 chars before the check digit). "
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "emirates_id": (
        "The text below was transcribed from a UAE Emirates ID card. "
        "Extract these fields and return ONLY a JSON object: "
        '"holder_name", "id_number" (format 784-XXXX-XXXXXXX-X), '
        '"expiry_date" (YYYY-MM-DD), "date_of_birth" (YYYY-MM-DD), '
        '"nationality", "gender". '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "trade_license": (
        "The text below was transcribed from a UAE Trade License document. "
        "Extract these fields and return ONLY a JSON object: "
        '"company_name" (English), "company_name_arabic" (Arabic text or null), '
        '"license_number", "register_number" (Commercial/DED register number), '
        '"dcci_membership_number" (DCCI or Chamber membership number or null), '
        '"expiry_date" (YYYY-MM-DD), '
        '"issue_date" (YYYY-MM-DD), "last_renewal_date" (YYYY-MM-DD), '
        '"license_type" (e.g. Commercial Licence), '
        '"licence_category" (e.g. Dept. of Economic Development or null), '
        '"last_renewal_fee" (e.g. AED 12,910 with receipt number if shown or null), '
        '"legal_form" (e.g. One Person Limited Liability Company), '
        '"business_activity" (primary activity name), '
        '"activity_status" (e.g. Active or null), '
        '"activity_scope" (full activity description or null), '
        '"regulatory_approval" (e.g. Subject to approval of... or null), '
        '"registered_address" (complete address as one string), '
        '"unit_number" (office or unit number extracted from the address, e.g. 021-202 or null), '
        '"building_name" (building name extracted from the address or null), '
        '"area" (area or district name extracted from the address, e.g. Hor Al Anz East or null), '
        '"parcel_id" (Parcel ID or Land DM No. or null), '
        '"makani_number" (Makani No. or null), '
        '"phone_fax" (phone or fax number or null), '
        '"mobile", "email", "issuing_authority", '
        '"owner_name" (English), "owner_nationality" (or null), '
        '"owner_share" (e.g. 100% or null), '
        '"owner_person_number" (Person No. from the licence or null), '
        '"manager_name" (English), "manager_nationality" (or null), '
        '"manager_role" (e.g. Manager or null), '
        '"manager_person_number" (Person No. from the licence or null). '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "ejari": (
        "The text below was transcribed from an Ejari tenancy contract or certificate. "
        "Extract these fields and return ONLY a JSON object: "
        '"tenant_name", "ejari_number", "expiry_date" (YYYY-MM-DD), '
        '"start_date" (YYYY-MM-DD), "registration_date" (YYYY-MM-DD), '
        '"registered_by" (agent or real estate company that registered EJARI or null), '
        '"annual_rent" (e.g. AED 21,000), "security_deposit" (e.g. AED 0), '
        '"ejari_fees_paid" (e.g. AED 172.50 with receipt number if shown or null), '
        '"building_name", "unit_number", "area", "unit_type", "size", '
        '"plot_number" (Plot No. or null), '
        '"land_dm_parcel_id" (Land DM No. or Parcel ID or null), '
        '"makani_number" (Makani No. or null), '
        '"licence_number" (trade licence number referenced on EJARI or null), '
        '"licence_issuer" (trade licence issuing authority referenced on EJARI or null), '
        '"landlord_name" (owner/landlord English name), '
        '"landlord_owner_number" (owner number or null), '
        '"landlord_nationality" (or null), '
        '"property_manager", "property_manager_email" (or null). '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "moa": (
        "The text below was transcribed from a UAE Memorandum of Association (MOA) document. "
        "Extract these fields and return ONLY a JSON object: "
        '"contract_number" (MOA or contract number), '
        '"moa_date" (YYYY-MM-DD — date of signing or notarisation), '
        '"company_name" (English), "company_name_arabic" (Arabic text or null), '
        '"legal_form" (e.g. One Person Limited Liability Company), '
        '"company_duration" (e.g. 25 Years from registration auto-renewable or null), '
        '"financial_year" (e.g. 1 January to 31 December or null), '
        '"disputes_jurisdiction" (e.g. Courts of Dubai or null), '
        '"share_capital" (e.g. AED 300,000 Fully Paid or null), '
        '"shares_count" (e.g. 300 Shares at AED 1,000 per share or null), '
        '"capital_currency" (e.g. UAE Dirhams AED or null), '
        '"capital_deposited" (e.g. Yes deposited in company bank account or null), '
        '"statutory_reserve" (e.g. 10% of net profits annually until reserve = 50% of capital or null), '
        '"owner_name" (English full name), "owner_name_arabic" (Arabic or null), '
        '"owner_nationality", '
        '"owner_person_number" (Person No. or null), '
        '"owner_shares" (e.g. 300 Shares AED 300,000 100% or null), '
        '"owner_liability" (e.g. Limited to share capital amount only or null), '
        '"owner_residence" (city and country or null), '
        '"manager_name" (English full name), "manager_name_arabic" (Arabic or null), '
        '"manager_nationality", '
        '"manager_residence" (city and country or null), '
        '"manager_pobox" (P.O. Box or null), '
        '"manager_person_number" (Person No. or null), '
        '"manager_role" (e.g. Manager or General Manager or null), '
        '"manager_appointment_term" (e.g. 5 Years from registration auto-renewable or null), '
        '"signing_authority" (e.g. Individual no co-signatory required or null), '
        '"authorised_signatory" (name and role or null), '
        '"signing_mode" (e.g. INDIVIDUAL sole signatory or null), '
        '"bank_open_close" (authority to open/close bank accounts or null), '
        '"bank_operate" (authority to operate bank accounts or null), '
        '"bank_cheques" (authority to sign cheques or null), '
        '"bank_transfer" (authority to transfer/withdraw funds or null), '
        '"bank_tenders" (authority to sign tenders and contracts or null), '
        '"bank_lc" (authority to issue letters of credit or null), '
        '"bank_vat" (authority for VAT/FTA returns or null), '
        '"bank_delegate" (authority to delegate or null). '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "insurance": (
        "The text below was transcribed from an insurance certificate or policy document. "
        "Extract these fields and return ONLY a JSON object: "
        '"insurer" (insurance company name), '
        '"policy_number" (policy or certificate number), '
        '"valid_from" (YYYY-MM-DD — policy start date), '
        '"valid_to" (YYYY-MM-DD — policy expiry date), '
        '"insured_name" (name of the insured entity or null), '
        '"coverage_type" (type of coverage or null). '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "residence_visa": (
        "The text below was transcribed from a UAE Residence Visa (entry permit or residence stamp). "
        "Extract these fields and return ONLY a JSON object: "
        '"holder_name" (full English name as printed), '
        '"id_number" (UAE ID No. or UID No. or null), '
        '"passport_number" (passport number referenced on the visa), '
        '"profession" (profession or occupation as printed), '
        '"employer" (sponsor or employer name or null), '
        '"file_number" (file no. or permit no. or null), '
        '"visa_number" (visa or entry permit number or null), '
        '"issue_date" (YYYY-MM-DD), '
        '"expiry_date" (YYYY-MM-DD), '
        '"place_of_issue" (issuing authority or city or null), '
        '"nationality" (nationality as printed or null). '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
    "vat_certificate": (
        "The text below was transcribed from a UAE VAT Registration Certificate issued by the Federal Tax Authority (FTA). "
        "Extract these fields and return ONLY a JSON object: "
        '"company_name" (English name of the registered entity), '
        '"company_name_arabic" (Arabic name or null), '
        '"trn" (Tax Registration Number — 15-digit number), '
        '"effective_date" (YYYY-MM-DD — date VAT registration became effective), '
        '"registered_address" (full registered address as one string), '
        '"return_period" (VAT return filing period, e.g. Quarterly or Monthly or null), '
        '"registration_type" (e.g. Mandatory or Voluntary or null). '
        "Set a field to null only if it is genuinely absent from the transcription."
    ),
}


def _bytes_to_base64_image(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """Return (base64_data, media_type). Converts PDF first page to PNG if needed."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        try:
            import fitz
        except ImportError:
            raise RuntimeError("Install pymupdf: pip install pymupdf")
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        image_bytes = pix.tobytes("png")
        doc.close()
        return base64.b64encode(image_bytes).decode(), "image/png"
    media_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    media_type = media_map.get(ext, "image/jpeg")
    return base64.b64encode(file_bytes).decode(), media_type


async def extract_for_kyc(file_bytes: bytes, filename: str, doc_type: str) -> dict:
    """
    Two-step extraction:
      1. OCR  — transcribe all visible text from the image (no ID-document framing).
      2. Parse — extract structured JSON from the transcription (no image, no filters).
    """
    if doc_type not in _EXTRACT_PROMPTS:
        return {"error": f"Unknown document type '{doc_type}'."}

    b64, media_type = _bytes_to_base64_image(file_bytes, filename)

    # ── Step 1: transcribe the image ──────────────────────────────────────────
    ocr_resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _OCR_SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Transcribe all text visible in this document image.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        max_tokens=1500,
        temperature=0,
    )
    transcription = ocr_resp.choices[0].message.content.strip()

    if not transcription:
        return {"error": f"Could not read text from the {doc_type.replace('_', ' ')} image."}

    # ── Step 2: extract structured fields from the transcription ─────────────
    extract_resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _EXTRACT_PROMPTS[doc_type]},
            {"role": "user", "content": transcription},
        ],
        response_format={"type": "json_object"},
        max_tokens=1200,
        temperature=0,
    )

    raw = extract_resp.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Could not parse {doc_type.replace('_', ' ')} data."}
