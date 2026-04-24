import base64
import json
import re
from datetime import date, datetime

from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY, DEEPSEEK_API_KEY

_openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
_deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

_MODEL = "gpt-4.1"


async def _chat_with_fallback(messages, max_tokens: int, temperature: float, response_format=None):
    """Try GPT-4.1 first; silently fall back to deepseek-chat on any error."""
    kwargs = dict(messages=messages, max_tokens=max_tokens, temperature=temperature)
    if response_format:
        kwargs["response_format"] = response_format
    try:
        return await _openai_client.chat.completions.create(model=_MODEL, **kwargs)
    except Exception:
        return await _deepseek_client.chat.completions.create(model="deepseek-chat", **kwargs)


# ── Step 1: bilingual OCR — transcribe English + Arabic text ─────────────────
_OCR_SYSTEM = (
    "You are a highly accurate multilingual OCR assistant. "
    "Transcribe EVERY piece of text visible in the image(s) exactly as it appears:\n"
    "- All English text: names, labels, numbers, dates, codes, addresses\n"
    "- All Arabic text (الأسماء، التواريخ، العناوين): transcribe Arabic characters exactly as printed\n"
    "- All machine-readable zones (MRZ): transcribe character by character including < symbols\n"
    "- All stamps, watermarks, headers, footers, margin text\n"
    "- All numbers: dates, monetary amounts, phone numbers, reference numbers, ID numbers\n\n"
    "Rules:\n"
    "1. Transcribe EXACTLY as printed — do not correct spelling or grammar\n"
    "2. Preserve line-by-line layout structure\n"
    "3. For bilingual text, transcribe BOTH languages on the same line if they appear together\n"
    "4. Do NOT skip, summarize, redact, or omit ANY text\n"
    "5. Output raw transcription only — no commentary or formatting\n"
    "6. If multiple pages are provided, separate with '--- PAGE BREAK ---'"
)


# ── Step 2: extract specific fields from the transcription ───────────────────
_PROMPTS = {
    "passport": (
        "You are an expert document data extractor. The text below was transcribed from a passport.\n"
        "The passport may contain text in English, Arabic, French, or multiple languages.\n\n"
        "Extract these fields and return ONLY a valid JSON object:\n\n"
        '- "expiry_date": Passport expiry date in YYYY-MM-DD format.\n'
        '  Look for labels: "Date of Expiry" / "تاريخ الانتهاء" / "Date d\'expiration".\n'
        "  MRZ fallback: line 2 positions 22-27 (YYMMDD) — prefix 20 for years < 70, 19 for >= 70.\n\n"
        '- "holder_name": Full name in ENGLISH.\n'
        '  Look for "Surname"/"Family Name" + "Given Names"/"First Name" labels.\n'
        "  Arabic passports may show الاسم/اللقب with English text beside them.\n"
        "  Combine surname + given names into one readable name (e.g., AHMED MOHAMMED ALI).\n"
        "  If ONLY Arabic name is visible, transliterate it to English.\n"
        "  MRZ fallback: P<COUNTRY_SURNAME<<GIVEN<NAMES — replace << with space, < with space, trim.\n\n"
        '- "passport_number": Alphanumeric passport number (typically 6-9 characters).\n'
        '  Look for "Passport No." / "رقم الجواز". MRZ: line 2, first 9 chars before the check digit.\n\n'
        "CRITICAL DATE RULES:\n"
        "- UAE/GCC documents commonly use DD/MM/YYYY format. ALWAYS convert to YYYY-MM-DD.\n"
        "- Example: 15/03/2028 means 15 March 2028 → output as 2028-03-15.\n"
        "- MRZ dates are YYMMDD — 280315 means 2028-03-15.\n"
        "- If a Hijri (هجري) date is shown alongside Gregorian, use the Gregorian date.\n\n"
        "Set a field to null ONLY if genuinely absent from the transcription."
    ),
    "emirates_id": (
        "You are an expert document data extractor. The text below was transcribed from a UAE Emirates ID card.\n"
        "The card is bilingual: Arabic text on the right, English on the left.\n\n"
        "Extract these fields and return ONLY a valid JSON object:\n\n"
        '- "expiry_date": in YYYY-MM-DD format.\n'
        '  Look for "Expiry Date:" / "تاريخ الانتهاء" on the front face.\n'
        "  MRZ fallback: line 2 positions 22-27 (YYMMDD) — prefix 20 for the year.\n\n"
        '- "holder_name": ENGLISH full name.\n'
        '  Look for the "Name:" label on the front. If ONLY Arabic name (الاسم) is visible, transliterate.\n'
        "  MRZ fallback: name appears on the second MRZ line after the ID number check digit.\n\n"
        '- "id_number": 15-digit UAE ID in format 784-XXXX-XXXXXXX-X.\n'
        "  Look for number starting with 784 on the front.\n"
        "  MRZ: line starting with IDARE, positions 6-20 are the ID digits.\n\n"
        "CRITICAL DATE RULES:\n"
        "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
        "- Example: 31/07/2028 → 2028-07-31.\n\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "trade_license": (
        "You are an expert document data extractor. The text below was transcribed from a UAE Trade License.\n"
        "Trade licenses are bilingual (Arabic + English), issued by DED or free zone authorities.\n\n"
        "Extract these fields and return ONLY a valid JSON object:\n\n"
        '- "expiry_date": License expiry date in YYYY-MM-DD.\n'
        '  Look for "Expiry Date" / "تاريخ الانتهاء".\n\n'
        '- "company_name": Company/trade name in English.\n'
        '  Look for "Trade Name" / "الاسم التجاري".\n'
        "  If ONLY Arabic company name is visible, transliterate it to English.\n\n"
        '- "license_number": The license number (رقم الرخصة).\n\n'
        "CRITICAL DATE RULES:\n"
        "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
        "- Example: 15/06/2025 → 2025-06-15.\n\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "ejari": (
        "You are an expert document data extractor. The text below was transcribed from an Ejari "
        "tenancy contract registration certificate.\n"
        "Ejari documents may be in English, Arabic, or both.\n\n"
        "Extract these fields and return ONLY a valid JSON object:\n\n"
        '- "expiry_date": Contract end date in YYYY-MM-DD.\n'
        '  Look for "Contract End Date" / "تاريخ انتهاء العقد".\n\n'
        '- "tenant_name": Tenant name in English.\n'
        '  Look for "Tenant" / "المستأجر". If ONLY Arabic name, transliterate.\n\n'
        '- "ejari_number": Ejari registration number (رقم إيجاري).\n\n'
        "CRITICAL DATE RULES:\n"
        "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n\n"
        "Set a field to null ONLY if genuinely absent."
    ),
}

# doc_type → (name_key, number_key) in GPT response
_FIELD_MAP = {
    "passport":      ("holder_name",  "passport_number"),
    "emirates_id":   ("holder_name",  "id_number"),
    "trade_license": ("company_name", "license_number"),
    "ejari":         ("tenant_name",  "ejari_number"),
}

_DOC_LABEL = {
    "passport":      "passport",
    "emirates_id":   "Emirates ID",
    "trade_license": "trade licence",
    "ejari":         "Ejari document",
}


def _bytes_to_base64_images(file_bytes: bytes, filename: str) -> list[tuple[str, str]]:
    """Return list of (base64_data, media_type) tuples. PDFs yield one tuple per page (up to 10 pages at 300 DPI)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise RuntimeError("Install pymupdf to process PDF documents: pip install pymupdf")
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        max_pages = min(len(doc), 10)
        for i in range(max_pages):
            pix = doc[i].get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            images.append((base64.b64encode(img_bytes).decode(), "image/png"))
        doc.close()
        return images

    media_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    media_type = media_map.get(ext, "image/jpeg")
    return [(base64.b64encode(file_bytes).decode(), media_type)]


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _months_between(d1: date, d2: date) -> int:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


async def check_document(file_bytes: bytes, filename: str, doc_type: str) -> dict:
    if doc_type not in _PROMPTS:
        return {"error": f"Unknown document type '{doc_type}'."}

    images = _bytes_to_base64_images(file_bytes, filename)
    label = _DOC_LABEL[doc_type]

    # ── Step 1: transcribe the image(s) — bilingual OCR ──────────────────────
    content_blocks = [
        {
            "type": "text",
            "text": "Transcribe all text visible in this document image. Include ALL Arabic and English text, every number, date, and code.",
        },
    ]
    for b64, media_type in images:
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"},
        })

    ocr_resp = await _chat_with_fallback(
        messages=[
            {"role": "system", "content": _OCR_SYSTEM},
            {"role": "user", "content": content_blocks},
        ],
        max_tokens=4000,
        temperature=0,
    )
    transcription = ocr_resp.choices[0].message.content.strip()

    if not transcription:
        return {"error": f"Could not read text from the {label}. Please upload a clearer image."}

    # ── Step 2: extract structured fields from the transcription ─────────────
    extract_resp = await _chat_with_fallback(
        messages=[
            {"role": "system", "content": _PROMPTS[doc_type]},
            {"role": "user", "content": transcription},
        ],
        response_format={"type": "json_object"},
        max_tokens=800,
        temperature=0,
    )

    raw = extract_resp.choices[0].message.content.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Could not parse {label} data. Please upload a clearer image."}

    name_key, number_key = _FIELD_MAP[doc_type]
    expiry_date = _parse_date(data.get("expiry_date"))

    if expiry_date is None:
        return {
            "error": "Could not read expiry date. Please upload a clearer scan.",
            "primary_name": data.get(name_key),
            "document_number": data.get(number_key),
        }

    today = date.today()
    months_remaining = _months_between(today, expiry_date)

    if months_remaining < 0:
        status = "expired"
    elif months_remaining < 6:
        status = "expiring_soon"
    else:
        status = "valid"

    return {
        "doc_type": doc_type,
        "expiry_date": expiry_date.strftime("%d %B %Y"),
        "months_remaining": months_remaining,
        "status": status,
        "primary_name": data.get(name_key),
        "document_number": data.get(number_key),
    }


async def check_passport(file_bytes: bytes, filename: str) -> dict:
    """Backward-compatible wrapper around check_document."""
    result = await check_document(file_bytes, filename, "passport")
    if "error" not in result:
        result["holder_name"] = result.pop("primary_name", None)
        result["passport_number"] = result.pop("document_number", None)
    return result
