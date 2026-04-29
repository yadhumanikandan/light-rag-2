"""Bilingual OCR step (gpt-5) — transcribes raw text from document images.

Framed as plain transcription so safety filters don't refuse identity documents.
"""
import re

from app.extractors._clients import openai, OCR_MODEL
from app.extractors._images import to_base64_images

OCR_SYSTEM = (
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

REFUSAL_PHRASES = (
    "i'm sorry", "i cannot", "i can't", "i am unable", "i'm unable",
    "unable to transcribe", "cannot transcribe", "sorry, i", "as an ai",
    "i'm not able", "i am not able",
)


def strip_json_fences(text: str) -> str:
    """Remove markdown ```json ... ``` fences sometimes wrapping JSON responses."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text


async def transcribe(files: list[tuple[bytes, str]]) -> str:
    """OCR every page of every file and return the concatenated transcription."""
    images = []
    for file_bytes, filename in files:
        images.extend(to_base64_images(file_bytes, filename))

    blocks = [
        {"type": "image_url",
         "image_url": {"url": f"data:{media};base64,{b64}", "detail": "high"}}
        for b64, media in images
    ]
    blocks.append({
        "type": "text",
        "text": "Transcribe all text visible in this document. "
                "Include ALL Arabic and English text, every number, date, and code.",
    })

    resp = await openai.chat.completions.create(
        model=OCR_MODEL,
        messages=[
            {"role": "system", "content": OCR_SYSTEM},
            {"role": "user", "content": blocks},
        ],
        reasoning_effort="minimal",
    )
    return (resp.choices[0].message.content or "").strip()


def is_refusal(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in REFUSAL_PHRASES)
