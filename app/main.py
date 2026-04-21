from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.passport import check_document, check_passport

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Document Expiry Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend")), name="static")

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
VALID_DOC_TYPES = {"passport", "emirates_id", "trade_license", "ejari"}


@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/check-document")
async def check_document_endpoint(
    file: UploadFile = File(...),
    doc_type: str = Form("passport"),
):
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown document type '{doc_type}'.")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a PDF, JPG, PNG, or WEBP image.",
        )

    file_bytes = await file.read()
    result = await check_document(file_bytes, file.filename, doc_type)

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    return result


@app.post("/check-passport")
async def check_passport_endpoint(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a PDF, JPG, PNG, or WEBP image.",
        )

    file_bytes = await file.read()
    result = await check_passport(file_bytes, file.filename)

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    return result
