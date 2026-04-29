# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Two tools for Taamul Credit Review Services, served from one FastAPI app on a local office network:

1. **Document Expiry Checker** — upload a scan, get back expiry date + validity status. Supports any of the KYC doc types listed below (passport / Emirates ID / trade licence / ejari are the common cases).
2. **KYC Report Generator** — upload up to 15 document types (multiple files per type allowed) and get back a styled NAAS-format Word document (.docx) with all extracted fields plus a preview JSON. Generated reports and original scans are archived to an SMB/NAS share automatically.

Supported KYC doc types: Passport, Emirates ID, Trade License, Ejari, MOA, Insurance, Residence Visa, VAT Certificate, Board Resolution, Power of Attorney (POA), Partners Annex, Certificate of Incorporation, Register of Shareholders, Register of Directors, Certificate of Good Standing.

## Commands

**Setup:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then add ANTHROPIC_API_KEY (required) and the NAS_* / DEEPSEEK_API_KEY entries described below
```

**Run (always from project root):**
```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

**Health check:**
```bash
curl http://127.0.0.1:8765/health
```

**Keep running after terminal close:**
```bash
screen -S taamul-passport
uvicorn app.main:app --host 0.0.0.0 --port 8765
# Detach: Ctrl+A then D  |  Re-attach: screen -r taamul-passport
```

There is no committed automated test suite. Verify changes with manual API calls against `/health`, `/check-document`, `/classify-documents`, and `/generate-kyc` using representative files.

## Architecture

```
app/config.py          → loads all env vars from .env
app/passport.py        → expiry-check flow: OCR (gpt-5) → extract (Claude) → date parsing + status logic
app/kyc_extractor.py   → full-field extraction + classify_document; same OCR→extract pattern, more fields
app/name_reconciler.py → cross-doc name reconciliation (Arabic ↔ English transliteration drift)
app/kyc_compliance.py  → pure-logic NAAS v4.0 analysis: validity, attestation, A-G checklist, flag list
app/kyc_generator.py   → builds styled NAAS DOCX from extracted + analysis data (python-docx)
app/nas_storage.py     → archives original scans + generated DOCX to SMB share (non-fatal)
app/main.py            → FastAPI app, all endpoints, multi-partner session cache
frontend/index.html    → single-page UI with tabs for both tools (no build step)
```

Files **not wired to the FastAPI app** (legacy artefacts from an earlier LightRAG-based version of the project): `app/ingest.py`, `app/rag.py`, `rag_storage/`, `documents/`, `uploads/`, `PLAN.md`, `upgrade.md`. Don't take cues from them when editing the current pipeline.

### Two-step OCR → Extract pipeline

Both `passport.py` and `kyc_extractor.py` use the same two-step approach to avoid safety-filter refusals on identity documents:

1. **OCR step** (image → plain text) — uses **OpenAI `gpt-5`** with a bilingual (Arabic + English) "transcribe all text" system prompt. No mention of identity documents. Multi-page PDFs send all pages (up to 10) at 300 DPI as separate images, separated by `--- PAGE BREAK ---`.
2. **Extract step** (plain text → JSON) — uses **Claude Sonnet 4.6 (`claude-sonnet-4-6`)** with a structured per-doctype extraction prompt. No image is sent in this step, so vision-based filters don't apply. Prompts are bilingual-aware and handle Arabic-only documents via transliteration.

`passport.py` falls back to **DeepSeek** (`deepseek-chat`) if the Claude extract step fails. `kyc_extractor.py` has no fallback.

### Multi-partner KYC flow (two-phase)

`/generate-kyc` may detect that a company has more than one non-corporate partner and that some are missing personal docs. In that case it does **not** generate the report — it returns `{needs_partner_docs: true, partners, extracted_data, session_id}` so the frontend can prompt for per-partner uploads.

- **Phase-1 state** is held in `_pending_sessions` (in-memory dict, 30-min TTL) keyed by a UUID `session_id`. Storing this in-process means the app cannot be horizontally scaled without an external session store.
- The frontend then calls **`/generate-kyc-complete`** with `session_id`, the original `extracted_json` (base64), and per-partner files named `partner_{idx}_{passport|emirates_id|residence_visa}`. That endpoint extracts the new files, merges them into `extracted["partner_personal_docs"]`, and falls through to the same `_generate_and_respond()` path used by single-partner uploads.

### Name reconciliation

Arabic-primary documents (MOA, Trade License, Partners Annex, Ejari) transliterate names into English inconsistently across LLM calls (e.g. رضوان → "Radwan" / "Rizwan" / "Rezwan"). `reconcile_names()` builds a canonical index from passport / EID / visa English names, then overrides transliterated names everywhere else. Match keys, in confidence order: (1) Emirates-ID digits, (2) Arabic token overlap, (3) English token overlap. **Always call `reconcile_names()` before `analyse_compliance()` or `generate_kyc_document()`** — both downstream consumers compare names and rely on canonical spellings.

### Compliance analysis

`kyc_compliance.analyse(extracted, today) → analysis` is pure logic — no LLM calls, no I/O. It produces validity per document, MOA banking-authority assessment, presence/POA decisions, shareholder classification, attestation status, the A-G checklist, and a typed flag list. Both `generate_kyc_document()` and the frontend preview consume this `analysis` dict.

### Request flows

**Expiry check:** Browser → `POST /check-document` → `check_document()` in `passport.py` → OCR → extract → expiry date + status JSON.

**Bulk classify (UI helper):** Browser → `POST /classify-documents` (many files) → parallel `classify_document()` calls → `{results: [{filename, doc_type, confidence, reason}, ...]}`.

**KYC report:** Browser → `POST /generate-kyc` (up to 15 named file fields, each accepting one or more files) → parallel `extract_for_kyc()` per doc type → `reconcile_names()` → multi-partner branch decision → either return `needs_partner_docs` or call `_generate_and_respond()`. The latter runs `analyse_compliance()`, builds the DOCX, builds the JSON preview, archives to NAS, and returns `{filename, nas_folder, report, docx}` (docx base64).

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/`                       | Serves `frontend/index.html` |
| GET  | `/health`                 | Health check |
| POST | `/check-document`         | Multipart `file` + `doc_type` → `{doc_type, expiry_date, months_remaining, status, primary_name, document_number}` |
| POST | `/classify-documents`     | Multipart many `files` → `{results: [{filename, doc_type, confidence, reason}, ...]}` |
| POST | `/generate-kyc`           | Multipart with named file fields (one or more files per field) → `{filename, nas_folder, report, docx}` **or** `{needs_partner_docs, partners, extracted_data, session_id}` |
| POST | `/generate-kyc-complete`  | Phase-2 of multi-partner flow: `session_id` + `extracted_json` (b64) + `partner_{idx}_{doc_type}` files → same response shape as `/generate-kyc` |
| POST | `/check-passport`         | Legacy passport-only endpoint → `{expiry_date, months_remaining, status, holder_name, passport_number}` |

**`doc_type` values (also valid as `/generate-kyc` field names):** `passport`, `emirates_id`, `trade_license`, `ejari`, `moa`, `insurance`, `residence_visa`, `vat_certificate`, `board_resolution`, `poa`, `partners_annex`, `certificate_of_incorporation`, `register_of_shareholders`, `register_of_directors`, `certificate_of_good_standing`.

`/generate-kyc` requires at least one file across any field. Each field is `Optional[List[UploadFile]]` so the frontend can post Emirates ID front+back, multiple passports for different partners, etc.

**Status values:** `valid` (≥ 6 months), `expiring_soon` (0–5 months), `expired` (negative `months_remaining`).

## Critical Constraints

- **Supported formats**: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp` — enforced in `main.py` and the frontend.
- **PDF handling**: PyMuPDF (`fitz`) renders all pages (up to 10) at 300 DPI to PNG before base64-encoding. Import is deferred to runtime — missing `pymupdf` raises `RuntimeError` on first PDF upload.
- **`months_remaining` can be negative** for expired documents — the frontend uses `Math.abs()` for display.
- **Frontend API calls**: use relative URLs (`fetch('/check-document', ...)`) — works behind any IP.
- **`primary_name` / `document_number`**: unified field names in `/check-document` response. The legacy `/check-passport` endpoint remaps these back to `holder_name` / `passport_number`.
- **Run from project root**: `main.py` resolves `frontend/` via `BASE_DIR = Path(__file__).resolve().parent.parent`.
- **NAS archiving is non-fatal**: if `smbprotocol` is missing or the NAS is unreachable, the KYC download still succeeds and `nas_folder` will be `null`.
- **Extractions run in parallel**: `asyncio.gather` in `/generate-kyc`, `/generate-kyc-complete`, and `/classify-documents` — every doc / partner doc is extracted concurrently.
- **Multi-partner session cache is in-process**: `_pending_sessions` lives in the uvicorn worker. Restarting the server or running multiple workers will drop / mis-route phase-1 sessions.
- **`reconcile_names()` must run before `analyse_compliance()`** and `generate_kyc_document()`. `_generate_and_respond()` already enforces this — preserve the ordering when refactoring.
- **Doc-type keys are load-bearing**: `passport`, `emirates_id`, `trade_license`, … appear in backend dicts, frontend form names, NAS folder layout, and DOCX templates. Don't rename without sweeping all four.

## Environment Variables

Defined in `.env` (the committed `.env.example` is minimal — these are the values actually consumed by `app/config.py`):

- `ANTHROPIC_API_KEY` — **required** for the Claude Sonnet 4.6 extract step in both tools.
- `OPENAI_API_KEY` — **required** for the `gpt-5` OCR step in both tools.
- `DEEPSEEK_API_KEY` — optional; used as the fallback extractor in `passport.py` only.
- `NAS_SERVER` (default `192.168.0.5`), `NAS_USER` (default `RTCR002`), `NAS_PASSWORD`, `NAS_SHARE` (default `BANKS`) — SMB archive target.
- `RAG_STORAGE_DIR` (default `rag_storage`) — only used by legacy `app/rag.py`; the live FastAPI app does not touch it.
