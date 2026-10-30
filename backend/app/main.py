import base64, binascii, csv, hmac, io, json, os, re, uuid
from pathlib import Path
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session
from .database import Base, SessionLocal, engine, get_db
from .models import Document
from .processing import detect_document_type, extract_fields, extract_line_items, extract_text, extraction_confidence, validate
from .schemas import DocumentOut, InvoiceUpdate

DATA_DIR = Path(os.getenv("DATA_DIR", "./data" )).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
MAX_BYTES = int(os.getenv("MAX_UPLOAD_MB", "15")) * 1024 * 1024
ALLOWED = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
APP_USERNAME = os.getenv("APP_USERNAME", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
STATIC_DIR = Path(os.getenv("STATIC_DIR", "./static")).resolve()
if AUTH_REQUIRED and (not APP_USERNAME or not APP_PASSWORD):
    raise RuntimeError("AUTH_REQUIRED=true needs APP_USERNAME and APP_PASSWORD")
if AUTH_REQUIRED and len(APP_PASSWORD) < 16:
    raise RuntimeError("APP_PASSWORD must be at least 16 characters when authentication is enabled")

app = FastAPI(
    title="DocuSense API",
    version="0.1.0",
    docs_url=None if AUTH_REQUIRED else "/docs",
    redoc_url=None if AUTH_REQUIRED else "/redoc",
    openapi_url=None if AUTH_REQUIRED else "/openapi.json",
)
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])


def _valid_basic_credentials(header: str | None) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    username_matches = hmac.compare_digest(username, APP_USERNAME)
    password_matches = hmac.compare_digest(password, APP_PASSWORD)
    return username_matches & password_matches


@app.middleware("http")
async def protect_api(request: Request, call_next):
    is_api = request.url.path.startswith("/api/")
    is_public_health = request.url.path == "/api/health"
    if AUTH_REQUIRED and is_api and not is_public_health and request.method != "OPTIONS":
        if not _valid_basic_credentials(request.headers.get("authorization")):
            return Response(
                content='{"detail":"Authentication required"}',
                status_code=401,
                media_type="application/json",
                headers={"Cache-Control": "no-store"},
            )
    response = await call_next(request)
    if AUTH_REQUIRED and is_api:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response

@app.on_event("startup")
def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True); UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    # Upgrade existing SQLite/PostgreSQL MVP databases without discarding document history.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("documents")}
        additions = {
            "document_type": "VARCHAR(30) NOT NULL DEFAULT 'invoice'",
            "duplicate_of_id": "INTEGER",
            "extraction_confidence": "TEXT NOT NULL DEFAULT '{}'",
            "line_items": "TEXT NOT NULL DEFAULT '[]'",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.exec_driver_sql(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
    _backfill_extraction_metadata()

@app.get("/api/health")
def health(): return {"status": "ok"}

@app.post("/api/documents", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await _process_upload(file, db)

@app.post("/api/documents/batch")
async def upload_documents(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    if not files:
        raise HTTPException(400, "Choose at least one file")
    if len(files) > 10:
        raise HTTPException(413, "Upload up to 10 files at a time")
    uploaded, failed = [], []
    for file in files:
        try:
            uploaded.append(await _process_upload(file, db))
        except HTTPException as exc:
            failed.append({"filename": file.filename or "unnamed file", "error": exc.detail})
    return {"uploaded": uploaded, "failed": failed}

async def _process_upload(file: UploadFile, db: Session):
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED:
        raise HTTPException(415, "Upload a PDF, PNG, or JPEG document")
    data = await file.read(MAX_BYTES + 1)
    if not data: raise HTTPException(400, "The uploaded file is empty")
    if len(data) > MAX_BYTES: raise HTTPException(413, f"File exceeds {MAX_BYTES // (1024*1024)} MB")
    if content_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(415, "The file content is not a valid PDF")
    if content_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(415, "The file content is not a valid PNG")
    if content_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(415, "The file content is not a valid JPEG")
    stored = f"{uuid.uuid4().hex}{ALLOWED[content_type]}"
    path = UPLOAD_DIR / stored
    path.write_bytes(data)
    try:
        text = extract_text(path, content_type)
        fields = extract_fields(text)
        document_type = detect_document_type(text)
        items = extract_line_items(text)
        confidence = extraction_confidence(text, fields, items)
        issues = validate(fields, document_type)
        display_name = re.split(r"[\\/]", file.filename or "invoice")[-1][:255] or "invoice"
        duplicate = None
        if fields.get("vendor") and fields.get("invoice_number"):
            duplicate = db.scalar(select(Document).where(
                func.lower(Document.vendor) == fields["vendor"].lower(),
                func.lower(Document.invoice_number) == fields["invoice_number"].lower(),
            ).order_by(Document.id).limit(1))
        doc = Document(filename=display_name, stored_name=stored,
            content_type=content_type, status="needs_review", document_type=document_type,
            duplicate_of_id=duplicate.id if duplicate else None, extracted_text=text,
            extraction_confidence=json.dumps(confidence), line_items=json.dumps(items),
            validation_issues=json.dumps(issues), **fields)
        db.add(doc); db.commit(); db.refresh(doc)
        return _out(doc)
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise

@app.get("/api/documents", response_model=list[DocumentOut])
def list_documents(q: str = Query("", max_length=120), status: str | None = None,
                   db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.created_at.desc())
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.filename.ilike(term), Document.vendor.ilike(term), Document.invoice_number.ilike(term)))
    if status in {"needs_review", "approved"}: stmt = stmt.where(Document.status == status)
    return [_out(d) for d in db.scalars(stmt).all()]

@app.get("/api/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    return _out(_get(document_id, db))

@app.patch("/api/documents/{document_id}", response_model=DocumentOut)
def update_document(document_id: int, payload: InvoiceUpdate, db: Session = Depends(get_db)):
    doc = _get(document_id, db)
    fields = payload.model_dump()
    issues = validate(fields, fields["document_type"])
    if fields["status"] == "approved" and issues:
        raise HTTPException(422, "Cannot approve invoice until these checks are fixed: " + "; ".join(issues))
    confidence = json.loads(doc.extraction_confidence or "{}")
    for key, value in fields.items():
        if key != "status" and getattr(doc, key) != value:
            confidence[key] = "reviewed"
        setattr(doc, key, value)
    doc.validation_issues = json.dumps(issues)
    doc.extraction_confidence = json.dumps(confidence)
    doc.duplicate_of_id = db.scalar(select(Document.id).where(
        Document.id != doc.id,
        func.lower(Document.vendor) == (doc.vendor or "").lower(),
        func.lower(Document.invoice_number) == (doc.invoice_number or "").lower(),
    ).order_by(Document.id).limit(1)) if doc.vendor and doc.invoice_number else None
    db.commit(); db.refresh(doc)
    return _out(doc)

@app.get("/api/documents/{document_id}/file")
def get_document_file(document_id: int, db: Session = Depends(get_db)):
    doc = _get(document_id, db)
    path = (UPLOAD_DIR / doc.stored_name).resolve()
    if path.parent != UPLOAD_DIR or not path.is_file():
        raise HTTPException(404, "Stored document file not found")
    return FileResponse(path, media_type=doc.content_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "sandbox"})

@app.get("/api/export.csv")
def export_csv(q: str = Query("", max_length=120), document_type: str | None = Query(None, pattern="^(invoice|receipt|other)$"),
               from_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
               to_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), db: Session = Depends(get_db)):
    docs = _export_query(db, q, document_type, from_date, to_date)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    keys = ["filename", "document_type", "vendor", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "status", "created_at"]
    writer.writerow(keys)
    for doc in docs: writer.writerow([_spreadsheet_safe(getattr(doc, k)) for k in keys])
    return StreamingResponse(iter(["\ufeff" + stream.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition":"attachment; filename=docusense-invoices.csv"})

@app.get("/api/export.xlsx")
def export_xlsx(q: str = Query("", max_length=120), document_type: str | None = Query(None, pattern="^(invoice|receipt|other)$"),
                from_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                to_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), db: Session = Depends(get_db)):
    try: from openpyxl import Workbook
    except ImportError: raise HTTPException(503, "Excel export dependency is not installed")
    docs = _export_query(db, q, document_type, from_date, to_date)
    keys = ["filename", "document_type", "vendor", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "status", "created_at"]
    wb = Workbook(); ws = wb.active; ws.title = "Approved invoices"
    ws.append([k.replace("_", " ").title() for k in keys])
    for doc in docs: ws.append([_spreadsheet_safe(getattr(doc, k)) for k in keys])
    output = io.BytesIO(); wb.save(output); output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition":"attachment; filename=docusense-invoices.xlsx"})

def _get(document_id: int, db: Session):
    doc = db.get(Document, document_id)
    if doc is None: raise HTTPException(404, "Document not found")
    return doc

def _out(doc: Document):
    data = {column.name: getattr(doc, column.name) for column in Document.__table__.columns}
    data["validation_issues"] = json.loads(doc.validation_issues or "[]")
    data["extraction_confidence"] = json.loads(doc.extraction_confidence or "{}")
    data["line_items"] = json.loads(doc.line_items or "[]")
    return DocumentOut.model_validate(data)

def _export_query(db: Session, q: str, document_type: str | None, from_date: str | None, to_date: str | None):
    stmt = select(Document).where(Document.status == "approved").order_by(Document.created_at)
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.filename.ilike(term), Document.vendor.ilike(term), Document.invoice_number.ilike(term)))
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if from_date:
        stmt = stmt.where(Document.invoice_date >= from_date)
    if to_date:
        stmt = stmt.where(Document.invoice_date <= to_date)
    return db.scalars(stmt).all()

def _backfill_extraction_metadata():
    """Populate the new derived review fields for records created by earlier MVP versions."""
    with SessionLocal() as db:
        documents = db.scalars(select(Document).order_by(Document.id)).all()
        for doc in documents:
            if not doc.extracted_text:
                continue
            if doc.document_type == "invoice":
                doc.document_type = detect_document_type(doc.extracted_text)
            fields = extract_fields(doc.extracted_text)
            for key in ("vendor", "invoice_number", "invoice_date", "due_date", "subtotal", "tax", "total"):
                if getattr(doc, key) in (None, "") and fields.get(key) is not None:
                    setattr(doc, key, fields[key])
            if not doc.line_items or doc.line_items == "[]":
                doc.line_items = json.dumps(extract_line_items(doc.extracted_text))
            if not doc.extraction_confidence or doc.extraction_confidence == "{}":
                current = {key: getattr(doc, key) for key in ("vendor", "invoice_number", "invoice_date", "due_date", "subtotal", "tax", "total")}
                doc.extraction_confidence = json.dumps(extraction_confidence(doc.extracted_text, current, json.loads(doc.line_items)))
            if doc.status == "needs_review":
                current = {key: getattr(doc, key) for key in ("vendor", "invoice_number", "invoice_date", "due_date", "subtotal", "tax", "total")}
                doc.validation_issues = json.dumps(validate(current, doc.document_type))
            if not doc.duplicate_of_id and doc.vendor and doc.invoice_number:
                doc.duplicate_of_id = db.scalar(select(Document.id).where(
                    Document.id < doc.id,
                    func.lower(Document.vendor) == doc.vendor.lower(),
                    func.lower(Document.invoice_number) == doc.invoice_number.lower(),
                ).order_by(Document.id).limit(1))
        db.commit()

def _spreadsheet_safe(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
