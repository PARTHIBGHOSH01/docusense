# DocuSense

DocuSense is a local-first document processing MVP. Upload one or several PDFs, PNGs, or JPEGs; identify invoices and receipts; extract fields and obvious line items; review the original beside the extracted data; correct and approve records; then export approved records as CSV or Excel with search, type, and invoice-date filters.

Extraction is rule based and does not call an LLM. Field signals (high, medium, unavailable) are heuristic guidance, not calibrated probabilities. Duplicate warnings compare normalized vendor and invoice/receipt reference. Digital PDF text extraction uses PyMuPDF. Image and scanned PDF OCR uses Tesseract when installed; otherwise the document is retained for manual review and fields may remain blank. Human review is part of the workflow.

## Run with Docker

1. Copy `.env.example` to `.env` and set a local PostgreSQL password.
2. Run `docker compose up --build`.
3. Open the app at http://localhost:5173. API docs are at http://localhost:8000/docs.

Docker Compose runs PostgreSQL, FastAPI, and the Vite frontend. Uploaded files and database data persist in named volumes. The OCR container includes Tesseract.

## Run locally

Requirements: Python 3.11+, Node.js 20+, and (optional) Tesseract OCR installed and available on PATH.

Backend (SQLite is the default):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend, in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite development server proxies `/api` calls to FastAPI on port 8000.

## Tests

```powershell
cd backend
pytest
```

## Workflow and API

- `POST /api/documents` — upload one PDF, PNG, or JPEG (15 MB default limit).
- `POST /api/documents/batch` — upload up to 10 files; returns successful records and per-file errors.
- `GET /api/documents` — search history with optional `q` and `status` filters.
- `GET /api/documents/{id}` — read a document and extracted text.
- `GET /api/documents/{id}/file` — stream the stored file for the in-app preview.
- `PATCH /api/documents/{id}` — update extracted fields and mark as needs review or approved.
- `GET /api/export.csv` and `GET /api/export.xlsx` — export approved records; optional `q`, `document_type`, `from_date`, and `to_date` filters apply to both.
- `GET /api/health` — liveness endpoint.

Invoice validation checks required vendor, invoice number, date, and total; receipts require vendor, date, and total; other documents can be reviewed without invoice-only fields. Financial records also check subtotal plus tax against total (two-cent tolerance) and reject negative amounts. Approval is rejected with a clear explanation if required checks still fail.

## File handling and limitations

Uploads are limited by size and accepted media type, checked against their file signature, assigned a random server-side name, and stored outside the web root. Preview access goes through a document endpoint; filesystem paths are never exposed. Existing MVP databases are upgraded additively at startup to preserve their records. This MVP does not include authentication, tenant isolation, malware scanning, audit logging, production secrets management, retention controls, or cloud deployment hardening. Do not expose it to untrusted users or place sensitive production documents in it without adding those controls. An Alembic migration workflow is not included yet.
