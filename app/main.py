import asyncio
import base64
import json
import logging
import re
import time
import uuid
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from app.kyc_compliance import analyse as analyse_compliance
from app.kyc_extractor import classify_document, extract_for_kyc
from app.kyc_generator import build_report_data, generate_kyc_document, identify_partners
from app.name_reconciler import reconcile_names
from app.nas_storage import save_to_nas
from app.passport import check_document, check_passport

BASE_DIR = Path(__file__).resolve().parent.parent
logger  = logging.getLogger(__name__)

# ── In-memory cache for multi-partner phase-1 data (30-min TTL) ──────────────
_pending_sessions: dict[str, dict] = {}
_SESSION_TTL = 1800  # seconds


def _cache_session(raw_files, extracted, company):
    """Store phase-1 data and return a session UUID."""
    sid = str(uuid.uuid4())
    _pending_sessions[sid] = {
        "raw_files": raw_files,
        "extracted": extracted,
        "company": company,
        "created_at": time.time(),
    }
    # Prune expired sessions
    now = time.time()
    expired = [k for k, v in _pending_sessions.items() if now - v["created_at"] > _SESSION_TTL]
    for k in expired:
        del _pending_sessions[k]
    return sid


def _get_session(sid: str) -> dict | None:
    sess = _pending_sessions.get(sid)
    if sess and time.time() - sess["created_at"] <= _SESSION_TTL:
        return sess
    return None


def _pop_session(sid: str) -> dict | None:
    sess = _get_session(sid)
    if sess:
        del _pending_sessions[sid]
    return sess

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
                   "residence_visa", "vat_certificate", "board_resolution", "poa",
                   "partners_annex",
                   # Corporate-shareholder KYC pack (Phase 2)
                   "certificate_of_incorporation", "register_of_shareholders",
                   "register_of_directors", "certificate_of_good_standing",
                   # Phase 3 — additional NAAS v4.0 document types
                   "free_zone_license", "dcci_membership", "renewal_receipt",
                   "audited_financials", "ubo_declaration", "specimen_signatures"}


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


@app.post("/classify-documents")
async def classify_documents_endpoint(files: List[UploadFile] = File(...)):
    """Auto-classify each uploaded file into one of the supported KYC doc types.
    Used by the bulk-upload UI so the system can ask 'what's missing' at a glance."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    payloads: list[tuple[bytes, str]] = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Please upload PDF, JPG, PNG, or WEBP.",
            )
        payloads.append((await f.read(), f.filename))

    tasks = [classify_document(b, n) for b, n in payloads]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out = []
    for (_, fname), res in zip(payloads, results):
        if isinstance(res, Exception):
            out.append({"filename": fname, "doc_type": "unknown",
                        "confidence": "low", "reason": str(res)})
        else:
            out.append({"filename": fname, **res})
    return {"results": out}


@app.post("/generate-kyc")
async def generate_kyc_endpoint(
    trade_license:      Optional[List[UploadFile]] = File(default=None),
    ejari:              Optional[List[UploadFile]] = File(default=None),
    moa:                Optional[List[UploadFile]] = File(default=None),
    insurance:          Optional[List[UploadFile]] = File(default=None),
    passport:           Optional[List[UploadFile]] = File(default=None),
    emirates_id:        Optional[List[UploadFile]] = File(default=None),
    residence_visa:     Optional[List[UploadFile]] = File(default=None),
    vat_certificate:    Optional[List[UploadFile]] = File(default=None),
    board_resolution:   Optional[List[UploadFile]] = File(default=None),
    poa:                Optional[List[UploadFile]] = File(default=None),
    partners_annex:     Optional[List[UploadFile]] = File(default=None),
    certificate_of_incorporation: Optional[List[UploadFile]] = File(default=None),
    register_of_shareholders:     Optional[List[UploadFile]] = File(default=None),
    register_of_directors:        Optional[List[UploadFile]] = File(default=None),
    certificate_of_good_standing: Optional[List[UploadFile]] = File(default=None),
    free_zone_license:            Optional[List[UploadFile]] = File(default=None),
    dcci_membership:              Optional[List[UploadFile]] = File(default=None),
    renewal_receipt:              Optional[List[UploadFile]] = File(default=None),
    audited_financials:           Optional[List[UploadFile]] = File(default=None),
    ubo_declaration:              Optional[List[UploadFile]] = File(default=None),
    specimen_signatures:          Optional[List[UploadFile]] = File(default=None),
):
    """
    Accept up to 15 document types and return a styled KYC Word document.
    Each field accepts one or more files (e.g. Emirates ID front + back as two images).
    At least one document must be provided.
    """
    uploads = {
        "trade_license":      trade_license,
        "ejari":               ejari,
        "moa":                 moa,
        "insurance":           insurance,
        "passport":            passport,
        "emirates_id":         emirates_id,
        "residence_visa":      residence_visa,
        "vat_certificate":     vat_certificate,
        "board_resolution":    board_resolution,
        "poa":                 poa,
        "partners_annex":      partners_annex,
        "certificate_of_incorporation": certificate_of_incorporation,
        "register_of_shareholders":     register_of_shareholders,
        "register_of_directors":        register_of_directors,
        "certificate_of_good_standing": certificate_of_good_standing,
        "free_zone_license":            free_zone_license,
        "dcci_membership":              dcci_membership,
        "renewal_receipt":              renewal_receipt,
        "audited_financials":           audited_financials,
        "ubo_declaration":              ubo_declaration,
        "specimen_signatures":          specimen_signatures,
    }

    # Validate that at least one document was uploaded
    if all(not f for f in uploads.values()):
        raise HTTPException(status_code=400, detail="Please upload at least one document.")

    # Validate extensions for every uploaded file
    for doc_type, upload_list in uploads.items():
        if upload_list:
            for upload in upload_list:
                ext = Path(upload.filename).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported file type '{ext}' for {doc_type}. Please upload PDF, JPG, PNG, or WEBP.",
                    )

    # Read all uploads into memory once; reuse bytes for both extraction and NAS archiving
    # doc_type → list of (filename, bytes) — supports multiple files per doc type
    raw_files: dict[str, list[tuple[str, bytes]]] = {}
    tasks = {}
    for doc_type, upload_list in uploads.items():
        if upload_list:
            file_list: list[tuple[bytes, str]] = []
            for upload in upload_list:
                file_bytes = await upload.read()
                file_list.append((file_bytes, upload.filename))
            raw_files[doc_type] = [(fname, fb) for fb, fname in file_list]
            tasks[doc_type] = extract_for_kyc(file_list, doc_type)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    extracted = {}
    for doc_type, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            print(f"[EXTRACT ERROR] {doc_type}: {result}", flush=True)
            extracted[doc_type] = {"error": str(result)}
        else:
            extracted[doc_type] = result

    # If user uploaded multiple personal docs in one go (one per partner),
    # GPT-5 returns a JSON array. Stash the list, promote first item as the
    # legacy "primary" dict so downstream code keeps working.
    multi_items: dict[str, list[dict]] = {}
    for dt in ("passport", "emirates_id", "residence_visa"):
        v = extracted.get(dt)
        if isinstance(v, list):
            items = [x for x in v if isinstance(x, dict) and not x.get("error")]
            if items:
                multi_items[dt] = items
                extracted[dt] = items[0]
            else:
                extracted[dt] = {}

    # Defensive: any other doc type that comes back as a list (e.g. multiple Ejari /
    # tenancy contracts, multiple insurance policies) — compliance + generator expect
    # a single dict per type. Promote first item to primary, stash full list under
    # `<dt>_all` for any future renderer that wants the complete set.
    for dt, v in list(extracted.items()):
        if dt in ("passport", "emirates_id", "residence_visa", "partner_personal_docs"):
            continue
        if isinstance(v, list):
            items = [x for x in v if isinstance(x, dict) and not x.get("error")]
            if items:
                extracted[f"{dt}_all"] = items
                extracted[dt] = items[0]
            else:
                extracted[dt] = {}

    # Pre-build partner_personal_docs from multi_items so the reconciler indexes
    # EVERY uploaded passport/EID/visa, not just the first of each kind.
    # Group items by holder_name — one entry per unique person.
    if multi_items:
        by_name: dict[str, dict] = {}
        for dt, items in multi_items.items():
            for item in items:
                hname = (item.get("holder_name") or "").strip()
                if not hname:
                    continue
                key = hname.upper()
                entry = by_name.setdefault(key, {"partner_name": hname})
                entry[dt] = item
        if by_name:
            extracted["partner_personal_docs"] = list(by_name.values())

    reconcile_names(extracted)

    today = date.today()

    # ── Multi-partner detection ────────────────────────────────────────────────
    partners = identify_partners(extracted)
    non_corporate = [p for p in partners if p.get("name")]

    # Re-key partner_personal_docs by canonical partner names from MOA. After
    # reconciliation both partner["name"] and item.holder_name should agree,
    # so _names_match succeeds and has_* flags become true → no phase 2.
    if multi_items and non_corporate:
        from app.kyc_generator import _names_match, _s
        new_ppd: list[dict] = []
        for partner in non_corporate:
            entry = {
                "partner_name": partner["name"],
                "partner_nationality": partner.get("nationality", ""),
                "share_percentage": partner.get("share_percentage", ""),
                "passport": None,
                "emirates_id": None,
                "residence_visa": None,
            }
            for dt, items in multi_items.items():
                for item in items:
                    holder = _s(item.get("holder_name", ""))
                    if holder and _names_match(partner["name"], holder):
                        entry[dt] = item
                        break
            new_ppd.append(entry)
            partner["has_passport"]       = bool(entry["passport"])
            partner["has_emirates_id"]    = bool(entry["emirates_id"])
            partner["has_residence_visa"] = bool(entry["residence_visa"])
        extracted["partner_personal_docs"] = new_ppd

    missing_docs = [p for p in non_corporate
                    if not (p["has_passport"] or p["has_emirates_id"])]

    if len(non_corporate) > 1 and missing_docs:
        # Cache raw files + extracted data for phase 2
        company = ""
        if extracted.get("trade_license") and not extracted["trade_license"].get("error"):
            raw = extracted["trade_license"].get("company_name") or ""
            company = " ".join(raw) if isinstance(raw, list) else str(raw)
        session_id = _cache_session(raw_files, extracted, company)

        print(f"[PARTNER] Detected {len(non_corporate)} partners, "
              f"{len(missing_docs)} missing docs → needs_partner_docs (session={session_id})",
              flush=True)

        return JSONResponse({
            "needs_partner_docs": True,
            "partners": non_corporate,
            "extracted_data": base64.b64encode(json.dumps(extracted).encode()).decode(),
            "session_id": session_id,
        })

    # ── Single-partner or all docs present: generate immediately ──────────────
    return await _generate_and_respond(extracted, raw_files, today)


async def _generate_and_respond(extracted: dict, raw_files: dict, today: date) -> JSONResponse:
    """Shared logic: generate DOCX, build preview, archive to NAS, return response."""
    reconcile_names(extracted)

    try:
        analysis = analyse_compliance(extracted, today)
    except Exception as exc:
        logger.exception("Compliance analysis failed: %s", exc)
        analysis = {"error": str(exc)}

    try:
        docx_bytes = generate_kyc_document(extracted, analysis, today)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate KYC document: {exc}")

    report = build_report_data(extracted, today, analysis=analysis)

    company = ""
    if extracted.get("trade_license") and not extracted["trade_license"].get("error"):
        raw = extracted["trade_license"].get("company_name") or ""
        company = " ".join(raw) if isinstance(raw, list) else str(raw)
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in company).strip().replace(" ", "_")
    filename = f"KYC_{safe}.docx" if safe else "KYC_Report.docx"

    nas_folder_name = company or f"Unknown_Company_{today.strftime('%Y%m%d')}"
    print(f"[NAS] raw_files collected: {list(raw_files.keys())}", flush=True)
    print(f"[NAS] company='{nas_folder_name}'  docx_filename='{filename}'", flush=True)

    nas_display = None
    nas_folder = save_to_nas(docx_bytes, filename, nas_folder_name, raw_files)
    if nas_folder:
        nas_display = nas_folder.rstrip("\\").split("\\")[-1]
        print(f"[NAS] save succeeded → {nas_folder}", flush=True)
    else:
        print(f"[NAS] save FAILED for '{filename}' — see error above", flush=True)

    return JSONResponse({
        "filename":   filename,
        "nas_folder": nas_display,
        "report":     report,
        "docx":       base64.b64encode(docx_bytes).decode(),
    })


@app.post("/generate-kyc-complete")
async def generate_kyc_complete_endpoint(request: Request):
    """
    Phase 2 of multi-partner KYC: accept per-partner personal documents
    plus previously extracted company data, and generate the final report.
    """
    form = await request.form()

    # ── Decode previously extracted data ──────────────────────────────────────
    extracted_b64 = form.get("extracted_json")
    if not extracted_b64:
        raise HTTPException(status_code=400, detail="Missing extracted_json.")
    try:
        extracted = json.loads(base64.b64decode(extracted_b64))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid extracted_json.")

    session_id = form.get("session_id", "")
    session = _pop_session(session_id) if session_id else None
    raw_files = session["raw_files"] if session else {}

    # ── Parse per-partner file uploads ────────────────────────────────────────
    partner_uploads: dict[int, dict[str, list]] = {}  # {idx: {doc_type: [UploadFile]}}
    for key in form:
        m = re.match(r"partner_(\d+)_(passport|emirates_id|residence_visa)", key)
        if not m:
            continue
        idx, doc_type = int(m.group(1)), m.group(2)
        upload = form.getlist(key)
        if not upload:
            continue
        # Validate extensions
        for f in upload:
            ext = Path(f.filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type '{ext}' for partner {idx} {doc_type}.",
                )
        partner_uploads.setdefault(idx, {})[doc_type] = upload

    # ── Extract per-partner docs in parallel ──────────────────────────────────
    extract_tasks = {}  # (idx, doc_type) → coroutine
    partner_raw: dict[str, list[tuple[str, bytes]]] = {}  # for NAS archiving

    for idx, docs in partner_uploads.items():
        for doc_type, uploads_list in docs.items():
            file_list: list[tuple[bytes, str]] = []
            raw_key = f"partner_{idx}_{doc_type}"
            partner_raw[raw_key] = []
            for f in uploads_list:
                fb = await f.read()
                file_list.append((fb, f.filename))
                partner_raw[raw_key].append((f.filename, fb))
            extract_tasks[(idx, doc_type)] = extract_for_kyc(file_list, doc_type)

    if extract_tasks:
        results = await asyncio.gather(*extract_tasks.values(), return_exceptions=True)
        partner_extractions: dict[int, dict] = {}  # idx → {doc_type: extracted_data}
        for (idx, doc_type), result in zip(extract_tasks.keys(), results):
            if isinstance(result, Exception):
                partner_extractions.setdefault(idx, {})[doc_type] = {"error": str(result)}
            else:
                partner_extractions.setdefault(idx, {})[doc_type] = result
    else:
        partner_extractions = {}

    # ── Build partner_personal_docs list ──────────────────────────────────────
    partners = identify_partners(extracted)
    non_corporate = [p for p in partners if p.get("name")]

    partner_personal_docs: list[dict] = []
    for i, partner in enumerate(non_corporate):
        entry = {
            "partner_name": partner["name"],
            "partner_nationality": partner.get("nationality", ""),
            "share_percentage": partner.get("share_percentage", ""),
        }
        # Assign initial upload's docs to the matching partner
        pp  = extracted.get("passport") or {}
        eid = extracted.get("emirates_id") or {}
        visa = extracted.get("residence_visa") or {}
        from app.kyc_generator import _names_match, _s
        pp_name   = _s(pp.get("holder_name", ""))
        eid_name  = _s(eid.get("holder_name", ""))
        visa_name = _s(visa.get("holder_name", ""))

        name = partner["name"]
        entry["passport"]       = pp   if (pp_name   and _names_match(name, pp_name))   else None
        entry["emirates_id"]    = eid  if (eid_name  and _names_match(name, eid_name))  else None
        entry["residence_visa"] = visa if (visa_name and _names_match(name, visa_name)) else None

        # Override with newly uploaded partner docs
        if i in partner_extractions:
            for doc_type in ("passport", "emirates_id", "residence_visa"):
                if doc_type in partner_extractions[i]:
                    entry[doc_type] = partner_extractions[i][doc_type]

        partner_personal_docs.append(entry)

    extracted["partner_personal_docs"] = partner_personal_docs

    # Merge partner raw files into the NAS archive
    raw_files.update(partner_raw)

    today = date.today()
    return await _generate_and_respond(extracted, raw_files, today)


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
