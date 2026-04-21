import base64
import json
import re
from datetime import date, datetime

from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_PROMPTS = {
    "passport": (
        "You are a document data extraction assistant. "
        "Given a passport image, extract the expiry date, holder name, and passport number. "
        "Return ONLY a JSON object with keys: "
        '"expiry_date" (YYYY-MM-DD), "holder_name" (string or null), "passport_number" (string or null). '
        "If you cannot determine a field, set it to null. Do not include any other text."
    ),
    "emirates_id": (
        "You are a document data extraction assistant. "
        "Given a UAE Emirates ID image, extract the expiry date, holder name, and ID number. "
        "Return ONLY a JSON object with keys: "
        '"expiry_date" (YYYY-MM-DD), "holder_name" (string or null), "id_number" (string or null). '
        "If you cannot determine a field, set it to null. Do not include any other text."
    ),
    "trade_license": (
        "You are a document data extraction assistant. "
        "Given a UAE Trade License document, extract the expiry or renewal date, company name, and license number. "
        "Return ONLY a JSON object with keys: "
        '"expiry_date" (YYYY-MM-DD), "company_name" (string or null), "license_number" (string or null). '
        "If you cannot determine a field, set it to null. Do not include any other text."
    ),
    "ejari": (
        "You are a document data extraction assistant. "
        "Given an Ejari tenancy contract or certificate, extract the contract end date (expiry), "
        "tenant name, and Ejari registration number. "
        "Return ONLY a JSON object with keys: "
        '"expiry_date" (YYYY-MM-DD), "tenant_name" (string or null), "ejari_number" (string or null). '
        "If you cannot determine a field, set it to null. Do not include any other text."
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

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _PROMPTS[doc_type]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"},
                    }
                ],
            },
        ],
        max_tokens=300,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

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
