# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Taamul Internal Knowledge Base — a private RAG-powered chat system for Taamul Credit Review Services. Staff upload documents (PDF, DOCX, TXT, MD) and query them via a web UI. Runs on a local office network with no internet exposure.

## Commands

**Setup:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in API keys
```

**Run (always from project root):**
```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

**Keep running after terminal close:**
```bash
screen -S taamul-kb
uvicorn app.main:app --host 0.0.0.0 --port 8765
# Detach: Ctrl+A then D  |  Re-attach: screen -r taamul-kb
```

**First-run ingestion:** Drop documents into `documents/`, then `POST /ingest-all`.

## Architecture

```
app/config.py     → loads .env variables
app/rag.py        → LightRAG singleton + async init
app/ingest.py     → text extraction (PDF/DOCX/TXT) + async insert into LightRAG
app/main.py       → FastAPI app with lifespan, REST endpoints
frontend/         → single index.html (no build step)
rag_storage/      → LightRAG graph + vector store (auto-created on first run)
documents/        → drop files here for bulk ingestion via POST /ingest-all
uploads/          → temp storage for files uploaded through the UI
```

**Request flow:** Browser → `POST /query` or `POST /upload` → FastAPI → LightRAG (`rag.aquery` / `rag.ainsert`) → DeepSeek LLM + OpenAI embeddings

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serves `frontend/index.html` |
| GET | `/health` | Health check |
| POST | `/query` | `{"question": str, "mode": "hybrid"}` → `{"answer": str, "mode": str}` |
| POST | `/upload` | Multipart file upload → ingests into LightRAG |
| POST | `/ingest-all` | Ingests all files in `DOCUMENTS_DIR` |

## Critical Constraints

- **LightRAG async API**: Use `rag.ainsert()` and `rag.aquery()` — the async methods. Do NOT use the synchronous `insert()`/`query()` inside FastAPI async routes.
- **Storage initialization**: `await rag.initialize_storages()` must be called once at startup — handled by `init_rag()` in the FastAPI `lifespan` context manager.
- **Query modes**: Only `local`, `global`, `hybrid` are valid. Never use `naive`.
- **DeepSeek base URL**: Must be exactly `https://api.deepseek.com` — no trailing slash.
- **Embedding dimension**: `text-embedding-3-small` outputs `1536` dims — this must match `EmbeddingFunc(embedding_dim=1536, ...)`.
- **`rag_storage/`**: Do not pre-create this directory; LightRAG creates it automatically.
- **Frontend API calls**: Always use relative URLs (`fetch('/query', ...)`) so the app works behind any IP address.
- **Run from project root**: `main.py` resolves `frontend/` and static paths using `BASE_DIR = Path(__file__).resolve().parent.parent`.

## Environment Variables

Defined in `.env` (see `.env.example`):
- `DEEPSEEK_API_KEY` — DeepSeek API key
- `OPENAI_API_KEY` — OpenAI API key (embeddings only)
- `RAG_STORAGE_DIR` — LightRAG working directory (default: `./rag_storage`)
- `UPLOAD_DIR` — temp upload path (default: `./uploads`)
- `DOCUMENTS_DIR` — bulk ingest source (default: `./documents`)
