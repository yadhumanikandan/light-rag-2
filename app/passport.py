import base64
import json
import re
from datetime import date, datetime

from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY, DEEPSEEK_API_KEY

_openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
_deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


async def _chat_with_fallback(messages, max_tokens: int, temperature: float, response_format=None):
    """Try GPT-4o first; silently fall back to deepseek-chat on any error."""
    kwargs = dict(messages=messages, max_tokens=max_tokens, temperature=temperature)
    if response_format:
        kwargs["response_format"] = response_format
    try:
        return await _openai_client.chat.completions.create(model="gpt-4o", **kwargs)
    except Exception:
        return await _deepseek_client.chat.completions.create(model="deepseek-chat", **kwargs)

# Step 1: generic OCR — no identity-document framing to avoid safety filters
_OCR_SYSTEM = (
    "You are an OCR assistant. Transcribe every line of text visible in the image "
    "exactly as it appears — all names, numbers, dates, codes, labels, and any "
    "machine-readable text at the bottom. Do not skip, summarise, or redact anything. "
    "Output the raw transcription as plain text only."
)

# Step 2: extract specific fields from the transcription (plain text, no image)
_PROMPTS = {
    "passport": (
        "The text below was transcribed from a passport document. "
        "Extract these fields and return ONLY a JSON object: "
        '"expiry_date" (YYYY-MM-DD), '
        '"holder_name" (full readable name — NOT the MRZ << format), '
        '"passport_number" (alphanumeric, typically 9 chars). '
        "Tip — MRZ line 1: P<COUNTRY_SURNAME<<GIVEN<<... → convert to readable name. "
        "MRZ line 2: first 9 chars are the passport number. "
        "Set a field to null only if genuinely absent."
    ),
    "emirates_id": (
        "The text below was transcribed from a UAE Emirates ID card. "
        "Extract these fields and return ONLY a JSON object: "
        '"expiry_date" (YYYY-MM-DD), "holder_name", "id_number". '
        "Set a field to null only if genuinely absent."
    ),
    "trade_license": (
        "The text below was transcribed from a UAE Trade License document. "
        "Extract these fields and return ONLY a JSON object: "
        '"expiry_date" (YYYY-MM-DD), "company_name", "license_number". '
        "Set a field to null only if genuinely absent."
    ),
    "ejari": (
        "The text below was transcribed from an Ejari tenancy contract or certificate. "
        "Extract these fields and return ONLY a JSON object: "
        '"expiry_date" (YYYY-MM-DD), "tenant_name", "ejari_number". '
        "Set a field to null only if genuinely absent."
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


def _bytes_to_base64_image(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """Return (base64_data, media_type). Converts PDF first page to PNG if needed."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise RuntimeError("Install pymupdf to process PDF documents: pip install pymupdf")
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


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
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

    b64, media_type = _bytes_to_base64_image(file_bytes, filename)
    label = _DOC_LABEL[doc_type]

    # ── Step 1: transcribe the image (no ID-document framing) ─────────────────
    ocr_resp = await _chat_with_fallback(
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
                        "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"},
                    },
                ],
            },
        ],
        max_tokens=600,
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
        max_tokens=400,
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
