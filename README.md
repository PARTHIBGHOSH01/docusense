# DocuSense

DocuSense is a local-first document intelligence portfolio project. Upload PDFs, PNGs, or JPEGs; extract invoice and receipt fields and obvious line items; check validation signals and possible duplicates; review the original beside the extracted data; correct and approve records; and export approved records as CSV or Excel.

Extraction is rule based and does not call an LLM. Confidence labels are heuristic guidance, not calibrated probabilities. Digital PDF text extraction uses PyMuPDF. Scanned PDFs and images use Tesseract OCR when available. Human review remains part of the workflow.

## Run locally with Docker Compose

Requirements: Docker Desktop.

```powershell
Copy-Item .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env` to a local development password, then run:

```powershell
docker compose up --build
```

Open the app at http://localhost:5173 and API docs at http://localhost:8000/docs. Docker Compose runs PostgreSQL, FastAPI, and the Vite frontend. The named volumes preserve the database and uploaded documents across local restarts.

## Run locally without Docker

Requirements: Python 3.11+, Node.js 20+, and optional Tesseract on PATH for scanned documents.

Backend, in one PowerShell window:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend, in another PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite server forwards `/api` requests to FastAPI on port 8000. SQLite is the default for this local mode.

## Free portfolio deployment on Render

The repository includes a Render Blueprint and a root Dockerfile that builds the React app and serves it with FastAPI on one origin. To deploy:

1. Push this repository to GitHub and connect GitHub to Render.
2. In Render, create a new **Blueprint** from the `render.yaml` file in this repository.
3. Keep the service on the **Free** plan. When prompted, enter a private `APP_USERNAME` and a long, unique `APP_PASSWORD` in Render's environment setup. Do not put these values in GitHub or share them in chat.
4. Wait for the build and health check to finish, then open the `onrender.com` URL. Sign in with the credentials you set in Render.

This is a free portfolio demo, not durable hosting. Render's free web service sleeps after 15 minutes without traffic and can take about a minute to wake. Its filesystem is temporary: uploaded documents and the SQLite history are deleted whenever the service sleeps, restarts, or redeploys. Do not upload real or sensitive invoices. See [Render's free instance limits](https://render.com/docs/free).

The API is protected with HTTP Basic authentication when `AUTH_REQUIRED=true`. Deployment disables the interactive API docs and requires credentials to be configured at startup. Local development leaves authentication off by default. The sample credentials are not stored in the repository.

## Tests

```powershell
cd backend
python -m pytest -q
```

Frontend production build:

```powershell
cd frontend
npm ci
npm run build
```

## Workflow and API

- `POST /api/documents` — upload one PDF, PNG, or JPEG (15 MB default limit).
- `POST /api/documents/batch` — upload up to 10 files and return per-file errors.
- `GET /api/documents` — search and filter document history.
- `GET /api/documents/{id}` — read extracted document data.
- `GET /api/documents/{id}/file` — preview the stored original.
- `PATCH /api/documents/{id}` — correct fields and mark a document approved or needing review.
- `GET /api/export.csv` and `GET /api/export.xlsx` — export approved records with optional filters.
- `GET /api/health` — public liveness endpoint for hosting health checks.

Invoice validation checks required vendor, invoice number, date, total, and subtotal/tax arithmetic. Receipts use receipt checks; other documents can be reviewed without invoice-only fields. Approval is rejected while required checks fail.

## Security and scope

Uploads are size limited, checked against accepted file signatures, assigned random server-side names, and stored outside the web root. Previews stream through an authenticated endpoint and never expose server filesystem paths. The deployed demo has one shared owner login; it does not provide multiple user accounts or tenant separation. It also lacks malware scanning, audit logging, retention controls, and production operations. The free deployment loses uploaded data when it sleeps or restarts. Use fictional sample invoices only.

The sample invoices in `outputs/demo_invoices/` are fictional test files. This repository does not currently include an open-source license.
