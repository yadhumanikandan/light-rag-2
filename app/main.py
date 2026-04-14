import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from lightrag import QueryParam
from app.rag import get_rag, init_rag
from app.ingest import ingest_file, ingest_directory
from app.config import UPLOAD_DIR, DOCUMENTS_DIR

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_rag()
    yield


app = FastAPI(title="Taamul Knowledge Base API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend")), name="static")


@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))


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


GREETINGS = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy"}


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if req.mode not in ["local", "global", "hybrid"]:
        raise HTTPException(status_code=400, detail="mode must be local, global, or hybrid")

    if req.question.strip().lower().rstrip("!.,?") in GREETINGS:
        return QueryResponse(
            answer="Hello! I'm the Taamul Knowledge Base assistant. Ask me anything about the documents in the knowledge base.",
            mode=req.mode,
        )

    rag = get_rag()

    try:
        answer = await rag.aquery(req.question, param=QueryParam(mode=req.mode))
        return QueryResponse(answer=answer or "I couldn't find a relevant answer in the knowledge base.", mode=req.mode)
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
    supported = [".pdf", ".docx", ".txt", ".md", ".pptx", ".xlsx", ".xls", ".csv"]
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
