# Repository Guidelines

## Project Structure & Module Organization
`app/` contains the FastAPI backend and core logic:
- `main.py`: API routes (`/`, `/health`, `/check-document`, `/generate-kyc`)
- `passport.py` and `kyc_extractor.py`: OCR + field extraction flows
- `kyc_generator.py`: DOCX report generation
- `nas_storage.py`: SMB/NAS archiving
- `config.py`: environment variable loading

`frontend/index.html` is the single-page UI (no frontend build step).  
`documents/`, `uploads/`, and `rag_storage/` are runtime data/work directories.  
`requirements.txt` and `.env.example` define dependencies and required configuration.

## Build, Test, and Development Commands
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Health check:
```bash
curl http://127.0.0.1:8765/health
```

## Coding Style & Naming Conventions
Use Python with PEP 8 defaults: 4-space indentation, `snake_case` for functions/variables, and `UPPER_CASE` for constants (for example `SUPPORTED_EXTENSIONS`). Keep route handlers async and return structured JSON errors via `HTTPException`.

Preserve existing doc-type keys (`passport`, `emirates_id`, `trade_license`, etc.) across backend and frontend form fields. In `frontend/index.html`, keep styles grouped by section and reuse CSS variables in `:root`.

## Testing Guidelines
There is currently no committed automated test suite. For each change, run manual API checks against `/health`, `/check-document`, and `/generate-kyc` with representative files.

When adding tests, use `pytest` under a new `tests/` directory:
- file naming: `test_<module>.py`
- test naming: `test_<behavior>`
- prioritize date parsing/status logic and endpoint validation paths.

## Commit & Pull Request Guidelines
Recent commit subjects are short and direct (for example: `initial`, `all documents`, `nas upload`). Follow that style with concise, imperative subjects and one logical change per commit.

For PRs, include:
- what changed and why
- affected endpoints/modules
- environment/config updates
- manual verification evidence (API output and UI screenshot when frontend changes)

## Security & Configuration Tips
Do not commit `.env`, customer documents, or generated runtime artifacts. Keep API keys and NAS credentials in environment variables only, and use sanitized sample files for demos or screenshots.
