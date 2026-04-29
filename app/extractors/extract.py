"""Two-step extraction orchestrator: OCR (gpt-5) → Claude Sonnet field parser."""
import json

from app.extractors._clients import claude, CLAUDE_MODEL
from app.extractors._ocr import strip_json_fences, transcribe, is_refusal
from app.extractors.prompts import PROMPTS


async def extract_for_kyc(files: list[tuple[bytes, str]], doc_type: str) -> dict:
    """
    1. OCR — transcribe all visible text (English + Arabic) from document images via gpt-5.
    2. Parse — extract structured JSON fields from the transcription via Claude Sonnet.

    Args:
        files:    list of (file_bytes, filename) tuples — one per uploaded file for this doc type.
        doc_type: document type key (must be in PROMPTS).
    """
    if doc_type not in PROMPTS:
        return {"error": f"Unknown document type '{doc_type}'."}

    transcription = await transcribe(files)
    print(f"[OCR transcription for {doc_type}]:\n{transcription[:800]}", flush=True)

    if not transcription:
        return {"error": f"Could not read text from the {doc_type.replace('_', ' ')} image."}
    if is_refusal(transcription):
        print(f"[OCR] Detected refusal for {doc_type}. Transcription: {transcription[:300]}", flush=True)
        return {"error": f"Could not read text from the {doc_type.replace('_', ' ')} image. Please upload a clearer scan."}

    resp = await claude.messages.create(
        model=CLAUDE_MODEL,
        system=PROMPTS[doc_type] + "\n\nRespond with ONLY a valid JSON object, no other text.",
        messages=[{"role": "user", "content": transcription}],
        max_tokens=2500,
        temperature=0,
    )

    raw = strip_json_fences(resp.content[0].text)
    print(f"[EXTRACT raw for {doc_type}]:\n{raw[:500]}", flush=True)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Could not parse {doc_type.replace('_', ' ')} data."}
