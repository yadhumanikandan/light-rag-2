# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Document Expiry Checker — a tool for Taamul Credit Review Services that accepts a document scan (PDF or image) and uses GPT-4o vision to extract the expiry date and holder/company details, then returns the validity status. Supported document types: **Passport**, **Emirates ID**, **Trade License**, **Ejari**. Runs on a local office network.

## Commands

**Setup:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in OPENAI_API_KEY
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
app/config.py     → loads OPENAI_API_KEY from .env
app/passport.py   → PDF/image → base64, per-doc-type GPT-4o prompts, date parsing, status logic
app/main.py       → FastAPI app, POST /check-document endpoint
frontend/         → single index.html with 4-tab doc type selector (no build step)
```

**Request flow:** Browser → `POST /check-document` (multipart + `doc_type` field) → FastAPI → `check_document()` → GPT-4o vision → parsed expiry + status → JSON response → frontend renders result card.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serves `frontend/index.html` |
| GET | `/health` | Health check |
| POST | `/check-document` | Multipart `file` + `doc_type` form field → `{doc_type, expiry_date, months_remaining, status, primary_name, document_number}` |
| POST | `/check-passport` | Legacy endpoint (passport only) → `{expiry_date, months_remaining, status, holder_name, passport_number}` |

**`doc_type` values:** `passport`, `emirates_id`, `trade_license`, `ejari`

**Status values:** `valid` (≥ 6 months remaining), `expiring_soon` (0–5 months), `expired` (negative months).

## Critical Constraints

- **Supported formats**: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp` — enforced in both `main.py` and the frontend.
- **PDF handling**: PyMuPDF (`fitz`) renders page 0 at 200 DPI to PNG before base64-encoding. If `pymupdf` is not installed, `check_document()` raises `RuntimeError` at runtime (not import time).
- **GPT-4o vision**: Uses `detail: "high"` for accuracy. Response is expected to be raw JSON; markdown code fences are stripped before `json.loads`. Each doc type has its own system prompt and expected JSON keys (see `_PROMPTS` and `_FIELD_MAP` in `passport.py`).
- **Date parsing**: `_parse_date()` tries multiple formats in order; falls back to a regex on ISO fragments. If expiry date cannot be parsed, a partial error dict is returned (not an exception).
- **`months_remaining` can be negative** for expired documents — the frontend uses `Math.abs()` for display.
- **Frontend API calls**: Uses relative URL `fetch('/check-document', ...)` — works behind any IP.
- **`primary_name` / `document_number`**: unified field names in `/check-document` response, replacing per-doc-type names. The legacy `/check-passport` endpoint still returns `holder_name` and `passport_number`.
- **Run from project root**: `main.py` resolves `frontend/` via `BASE_DIR = Path(__file__).resolve().parent.parent`.

## Environment Variables

Defined in `.env` (see `.env.example`):
- `OPENAI_API_KEY` — required for GPT-4o vision calls
