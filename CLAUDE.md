# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Two tools for Taamul Credit Review Services, served from one FastAPI app on a local office network:

1. **Document Expiry Checker** — upload a scan, get back expiry date + validity status. Supports: Passport, Emirates ID, Trade License, Ejari.
2. **KYC Report Generator** — upload up to 8 document scans, get back a styled Word document (.docx) with all extracted fields plus a preview JSON. Supports: Passport, Emirates ID, Trade License, Ejari, MOA, Insurance, Residence Visa, VAT Certificate. Generated reports and original scans are archived to an SMB/NAS share automatically.

## Commands

**Setup:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in OPENAI_API_KEY and optional keys below
```

**Run (always from project root):**
```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

**Keep running after terminal close:**
```bash
screen -S taamul-passport
uvicorn app.main:app --host 0.0.0.0 --port 8765
# Detach: Ctrl+A then D  |  Re-attach: screen -r taamul-passport
```

## Architecture

```
app/config.py         → loads all env vars from .env
app/passport.py       → expiry-check flow: two-step OCR→extract, date parsing, status logic
app/kyc_extractor.py  → full-field extraction flow (same two-step OCR→extract, more fields)
app/kyc_generator.py  → builds styled DOCX from extracted data (python-docx, 17-section NAAS format)
app/nas_storage.py    → archives original scans + generated DOCX to SMB share (non-fatal)
app/main.py           → FastAPI app, all endpoints
frontend/             → single index.html with tabs for both tools (no build step)
```

### Two-Step OCR Pipeline (used by both tools)

Both `passport.py` and `kyc_extractor.py` use the same two-step approach to avoid safety-filter refusals on identity documents:

1. **OCR step** (image → plain text): sends the image(s) with a bilingual (Arabic + English) "transcribe all text" prompt — no mention of identity documents. Multi-page PDFs send all pages (up to 10) as separate images at 300 DPI.
2. **Extract step** (plain text → JSON): sends only the transcription with a structured extraction prompt; no image, so vision-based filters don't apply. Prompts are bilingual-aware and handle Arabic-only documents via transliteration.

`passport.py` uses GPT-4.1 with a DeepSeek fallback (`_chat_with_fallback`). `kyc_extractor.py` uses GPT-4.1 only (no fallback).

### Request Flows

**Expiry check:** Browser → `POST /check-document` → `check_document()` in `passport.py` → two-step OCR → expiry date + status JSON.

**KYC report:** Browser → `POST /generate-kyc` (up to 8 files) → parallel `extract_for_kyc()` calls (one per uploaded doc) → `generate_kyc_document()` → DOCX bytes + `build_report_data()` preview → NAS archive → response with `{filename, nas_folder, report, docx}` (docx is base64).

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serves `frontend/index.html` |
| GET | `/health` | Health check |
| POST | `/check-document` | Multipart `file` + `doc_type` → `{doc_type, expiry_date, months_remaining, status, primary_name, document_number}` |
| POST | `/generate-kyc` | Multipart with named file fields (see below) → `{filename, nas_folder, report, docx}` |
| POST | `/check-passport` | Legacy passport-only endpoint → `{expiry_date, months_remaining, status, holder_name, passport_number}` |

**`/check-document` `doc_type` values:** `passport`, `emirates_id`, `trade_license`, `ejari`

**`/generate-kyc` file field names:** `trade_license`, `ejari`, `moa`, `insurance`, `passport`, `emirates_id`, `residence_visa`, `vat_certificate` — all optional, at least one required.

**Status values:** `valid` (≥ 6 months), `expiring_soon` (0–5 months), `expired` (negative months remaining).

## Critical Constraints

- **Supported formats**: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp` — enforced in `main.py` and the frontend.
- **PDF handling**: PyMuPDF (`fitz`) renders all pages (up to 10) at 300 DPI to PNG before base64-encoding. Import is deferred to runtime — missing `pymupdf` raises `RuntimeError` on first PDF upload.
- **`months_remaining` can be negative** for expired documents — the frontend uses `Math.abs()` for display.
- **Frontend API calls**: Use relative URLs (`fetch('/check-document', ...)`) — works behind any IP.
- **`primary_name` / `document_number`**: unified field names in `/check-document` response. The legacy `/check-passport` endpoint remaps these back to `holder_name` / `passport_number`.
- **Run from project root**: `main.py` resolves `frontend/` via `BASE_DIR = Path(__file__).resolve().parent.parent`.
- **NAS archiving is non-fatal**: if `smbprotocol` is not installed or the NAS is unreachable, the KYC download still succeeds; `nas_folder` in the response will be `null`.
- **KYC extractions run in parallel**: `asyncio.gather` is used in `/generate-kyc` — each document is extracted concurrently.

## Environment Variables

Defined in `.env`:
- `OPENAI_API_KEY` — required for GPT-4.1 calls in both tools
- `DEEPSEEK_API_KEY` — optional; used as fallback in `passport.py` when GPT-4.1 fails
- `NAS_SERVER` — NAS IP (default: `192.168.0.5`)
- `NAS_USER` — SMB username (default: `RTCR002`)
- `NAS_PASSWORD` — SMB password
- `NAS_SHARE` — SMB share name (default: `BANKS`)
