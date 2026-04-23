import logging
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.kyc_extractor import extract_for_kyc
from app.kyc_generator import generate_kyc_document
from app.nas_storage import save_to_nas
from app.passport import check_document, check_passport

BASE_DIR = Path(__file__).resolve().parent.parent
logger  = logging.getLogger(__name__)

app = FastAPI(title="Document Expiry Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend")), name="static")

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
VALID_DOC_TYPES = {"passport", "emirates_id", "trade_license", "ejari", "moa", "insurance",
                   "residence_visa", "vat_certificate"}


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


@app.post("/generate-kyc")
async def generate_kyc_endpoint(
    trade_license:   Optional[UploadFile] = File(default=None),
    ejari:           Optional[UploadFile] = File(default=None),
    moa:             Optional[UploadFile] = File(default=None),
    insurance:       Optional[UploadFile] = File(default=None),
    passport:        Optional[UploadFile] = File(default=None),
    emirates_id:     Optional[UploadFile] = File(default=None),
    residence_visa:  Optional[UploadFile] = File(default=None),
    vat_certificate: Optional[UploadFile] = File(default=None),
):
    """
    Accept up to 8 document scans and return a styled KYC Word document.
    At least one document must be provided.
    """
    uploads = {
        "trade_license":   trade_license,
        "ejari":           ejari,
        "moa":             moa,
        "insurance":       insurance,
        "passport":        passport,
        "emirates_id":     emirates_id,
        "residence_visa":  residence_visa,
        "vat_certificate": vat_certificate,
    }

    # Validate that at least one document was uploaded
    if all(f is None for f in uploads.values()):
        raise HTTPException(status_code=400, detail="Please upload at least one document.")

    # Validate extensions
    for doc_type, upload in uploads.items():
        if upload is not None:
            ext = Path(upload.filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type '{ext}' for {doc_type}. Please upload PDF, JPG, PNG, or WEBP.",
                )

    # Read all uploads into memory once; reuse bytes for both extraction and NAS archiving
    import asyncio
    raw_files: dict[str, tuple[str, bytes]] = {}   # doc_type → (filename, bytes)
    tasks = {}
    for doc_type, upload in uploads.items():
        if upload is not None:
            file_bytes = await upload.read()
            raw_files[doc_type] = (upload.filename, file_bytes)
            tasks[doc_type] = extract_for_kyc(file_bytes, upload.filename, doc_type)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    extracted = {}
    for doc_type, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            extracted[doc_type] = {"error": str(result)}
        else:
            extracted[doc_type] = result

    # Generate the DOCX
    try:
        docx_bytes = generate_kyc_document(extracted, date.today())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate KYC document: {exc}")

    # Build a safe filename from company name
    company = ""
    if extracted.get("trade_license") and not extracted["trade_license"].get("error"):
        company = extracted["trade_license"].get("company_name") or ""
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in company).strip().replace(" ", "_")
    filename = f"KYC_{safe}.docx" if safe else "KYC_Report.docx"

    # ── Archive to NAS (non-fatal: user still gets the download on NAS failure) ──
    nas_folder_name = company or f"Unknown_Company_{date.today().strftime('%Y%m%d')}"
    print(f"[NAS] raw_files collected: {list(raw_files.keys())}", flush=True)
    print(f"[NAS] company='{nas_folder_name}'  docx_filename='{filename}'", flush=True)

    response_headers: dict[str, str] = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    nas_folder = save_to_nas(docx_bytes, filename, nas_folder_name, raw_files)
    if nas_folder:
        nas_display = nas_folder.rstrip("\\").split("\\")[-1]
        response_headers["X-NAS-Folder"] = nas_display
        print(f"[NAS] save succeeded → {nas_folder}", flush=True)
    else:
        print(f"[NAS] save FAILED for '{filename}' — see error above", flush=True)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=response_headers,
    )


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
