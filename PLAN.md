# Taamul Internal Knowledge Base — LightRAG Build Plan

## What We're Building

A private internal knowledge base for Taamul Credit Review Services. Staff can upload company documents (PDFs, Word docs, text files) and chat with them using natural language. Powered by LightRAG (graph-based RAG) with DeepSeek as the LLM and OpenAI for embeddings. Runs locally on the HPE ProLiant server — accessible only on the office network by IP address. No internet exposure, no domain, no SSL needed.

---

## Tech Stack

- **Backend**: Python (FastAPI)
- **RAG Engine**: `lightrag-hku`
- **LLM**: DeepSeek (`deepseek-chat`) via API
- **Embeddings**: OpenAI (`text-embedding-3-small`) via API
- **Frontend**: Single HTML file (vanilla JS, no build step needed)
- **Access**: Direct by IP on local office network (e.g. `http://192.168.x.x:8765`)

---

## Project Structure

```
/opt/taamul-kb/
├── app/
│   ├── main.py              # FastAPI app
│   ├── rag.py               # LightRAG initialization and query logic
│   ├── ingest.py            # Document ingestion logic
│   └── config.py            # Environment config loader
├── documents/               # Drop documents here to ingest
├── rag_storage/             # LightRAG working directory (graph + vectors)
├── uploads/                 # Temporary upload storage
├── frontend/
│   └── index.html           # Chat UI
├── .env                     # API keys (never commit)
└── requirements.txt
```

---

## Step 1 — Environment Setup

Create the project directory:

```bash
mkdir -p /opt/taamul-kb/{app,documents,rag_storage,uploads,frontend}
cd /opt/taamul-kb
python3 -m venv venv
source venv/bin/activate
```

Create `requirements.txt`:

```
lightrag-hku
fastapi
uvicorn[standard]
python-multipart
python-dotenv
openai
httpx
aiofiles
pypdf2
python-docx
```

Install:

```bash
pip install -r requirements.txt
```

---

## Step 2 — Environment Variables

Create `.env` in `/opt/taamul-kb/`:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
RAG_STORAGE_DIR=/opt/taamul-kb/rag_storage
UPLOAD_DIR=/opt/taamul-kb/uploads
DOCUMENTS_DIR=/opt/taamul-kb/documents
```

---

## Step 3 — Config Loader (`app/config.py`)

```python
from dotenv import load_dotenv
import os

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
RAG_STORAGE_DIR = os.getenv("RAG_STORAGE_DIR", "./rag_storage")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", "./documents")
```

---

## Step 4 — LightRAG Initialization (`app/rag.py`)

This is the core file. It sets up LightRAG with DeepSeek as LLM and OpenAI for embeddings.

```python
import asyncio
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache, openai_embedding
from lightrag.utils import EmbeddingFunc
from app.config import DEEPSEEK_API_KEY, OPENAI_API_KEY, RAG_STORAGE_DIR
import numpy as np

async def deepseek_complete(
    prompt, system_prompt=None, history_messages=[], **kwargs
):
    return await openai_complete_if_cache(
        "deepseek-chat",
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        **kwargs,
    )

async def openai_embed(texts):
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return np.array([item.embedding for item in response.data])

def get_rag_instance():
    rag = LightRAG(
        working_dir=RAG_STORAGE_DIR,
        llm_model_func=deepseek_complete,
        embedding_func=EmbeddingFunc(
            embedding_dim=1536,
            max_token_size=8192,
            func=openai_embed,
        ),
    )
    return rag

# Singleton instance
_rag_instance = None

def get_rag():
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = get_rag_instance()
    return _rag_instance
```

---

## Step 5 — Document Ingestion (`app/ingest.py`)

Handles extracting text from PDF, DOCX, and TXT files, then inserting into LightRAG.

```python
import os
import asyncio
from pathlib import Path
from app.rag import get_rag

def extract_text_from_pdf(filepath: str) -> str:
    import PyPDF2
    text = ""
    with open(filepath, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text

def extract_text_from_docx(filepath: str) -> str:
    from docx import Document
    doc = Document(filepath)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])

def extract_text_from_txt(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def extract_text(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in [".docx", ".doc"]:
        return extract_text_from_docx(filepath)
    elif ext in [".txt", ".md"]:
        return extract_text_from_txt(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

async def ingest_file(filepath: str) -> dict:
    """Extract text from file and insert into LightRAG."""
    rag = get_rag()
    filename = Path(filepath).name
    
    try:
        text = extract_text(filepath)
        if not text.strip():
            return {"success": False, "error": "File appears to be empty or unreadable"}
        
        # LightRAG insert is synchronous, run in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, rag.insert, text)
        
        return {"success": True, "filename": filename, "chars": len(text)}
    except Exception as e:
        return {"success": False, "filename": filename, "error": str(e)}

async def ingest_directory(directory: str) -> list:
    """Ingest all supported files in a directory."""
    results = []
    supported = [".pdf", ".docx", ".doc", ".txt", ".md"]
    for f in Path(directory).iterdir():
        if f.suffix.lower() in supported:
            result = await ingest_file(str(f))
            results.append(result)
    return results
```

---

## Step 6 — FastAPI Backend (`app/main.py`)

Full REST API with endpoints for uploading documents, querying, and checking status.

```python
import os
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from lightrag import QueryParam
from app.rag import get_rag
from app.ingest import ingest_file, ingest_directory
from app.config import UPLOAD_DIR, DOCUMENTS_DIR

app = FastAPI(title="Taamul Knowledge Base API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
app.mount("/static", StaticFiles(directory="/opt/taamul-kb/frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("/opt/taamul-kb/frontend/index.html")

# --- Health check ---

@app.get("/health")
async def health():
    return {"status": "ok"}

# --- Query endpoint ---

class QueryRequest(BaseModel):
    question: str
    mode: str = "hybrid"  # local, global, hybrid

class QueryResponse(BaseModel):
    answer: str
    mode: str

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if req.mode not in ["local", "global", "hybrid"]:
        raise HTTPException(status_code=400, detail="mode must be local, global, or hybrid")
    
    rag = get_rag()
    
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None,
            lambda: rag.query(req.question, param=QueryParam(mode=req.mode))
        )
        return QueryResponse(answer=answer, mode=req.mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Upload endpoint ---

class IngestResponse(BaseModel):
    success: bool
    filename: str
    chars: int = 0
    error: str = ""

@app.post("/upload", response_model=IngestResponse)
async def upload_document(file: UploadFile = File(...)):
    supported = [".pdf", ".docx", ".doc", ".txt", ".md"]
    ext = Path(file.filename).suffix.lower()
    
    if ext not in supported:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {supported}")
    
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, file.filename)
    
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    result = await ingest_file(save_path)
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Ingestion failed"))
    
    return IngestResponse(**result)

# --- Bulk ingest from documents folder ---

@app.post("/ingest-all")
async def ingest_all():
    """Ingest all files in the /documents directory."""
    results = await ingest_directory(DOCUMENTS_DIR)
    return {"results": results, "total": len(results)}
```

---

## Step 7 — Frontend (`frontend/index.html`)

Build a clean, professional dark-themed chat interface. It must:

- Have a header with "Taamul Knowledge Base" and the company logo text
- Have a chat window showing conversation history (user messages on right, AI on left)
- Have a text input with a Send button at the bottom
- Have a small mode selector (Local / Global / Hybrid) — default to Hybrid
- Have an upload button (paperclip icon) that lets staff upload documents
- Show a loading spinner when waiting for the AI response
- Show upload progress when a file is being ingested
- Use a dark navy/charcoal color scheme with gold accents (professional finance look)
- Use Google Fonts — `Playfair Display` for the header, `DM Sans` for body text
- Be fully responsive (works on mobile too)
- On page load, show a welcome message: "Welcome to Taamul Knowledge Base. Ask me anything about our policies, processes, or client information."
- Store conversation history in memory (JS array) and send it in context visually (just display it, not to the API — each query is independent)

All API calls go to `/query` (POST) and `/upload` (POST) on the same origin.

The frontend is a **single `index.html` file** with embedded CSS and JS — no build step, no frameworks.

---

## Step 8 — Running Locally

No Nginx, no systemd, no SSL needed. Just activate the venv and run:

```bash
cd /opt/taamul-kb
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Anyone on the office network can now open their browser and go to:

```
http://<server-local-ip>:8765
```

To find the server's local IP:

```bash
ip addr show | grep "inet " | grep -v 127.0.0.1
```

Use that IP address. Share it with the team — they just bookmark it in their browser.

**To keep it running after closing the terminal**, use a simple screen session:

```bash
screen -S taamul-kb
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
# Press Ctrl+A then D to detach
# To re-attach: screen -r taamul-kb
```

---

## Step 9 — First Run & Testing

1. Drop a test document into `/opt/taamul-kb/documents/`
2. Hit `POST /ingest-all` once to build the knowledge graph
3. Open the browser at `http://<server-local-ip>:8765` and ask a question

The first query after ingestion will be slow (30–60 seconds) as LightRAG builds its graph. Subsequent queries are faster.

---

## Important Notes for Claude Code

- The `app/` directory must have an `__init__.py` (empty file) so Python treats it as a package
- LightRAG's `insert()` and `query()` methods are **synchronous** — always wrap them in `loop.run_in_executor(None, ...)` inside async FastAPI routes
- The `rag_storage/` directory will be created automatically by LightRAG on first run — do not pre-create it
- Do NOT use `QueryParam(mode="naive")` — stick to `local`, `global`, or `hybrid`
- DeepSeek base URL must be exactly `https://api.deepseek.com` (no trailing slash)
- OpenAI embedding dim for `text-embedding-3-small` is `1536` — this must match the `EmbeddingFunc` config
- The frontend must use `fetch('/query', ...)` with relative URLs so it works behind any domain
- Handle the case where LightRAG returns an empty string or error gracefully in the frontend

---

## Final Directory Verification Checklist

Before running, confirm:

- [ ] `.env` exists with all 4 variables filled
- [ ] `app/__init__.py` exists (empty)
- [ ] `rag_storage/` directory exists and is writable
- [ ] `uploads/` directory exists
- [ ] `documents/` directory exists
- [ ] `frontend/index.html` exists
- [ ] `requirements.txt` installed in venv
- [ ] Server is reachable on the local network at port 8765
