from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="needs_review", nullable=False)
    document_type: Mapped[str] = mapped_column(String(30), default="invoice", nullable=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer)
    vendor: Mapped[str | None] = mapped_column(String(255))
    invoice_number: Mapped[str | None] = mapped_column(String(120))
    invoice_date: Mapped[str | None] = mapped_column(String(40))
    due_date: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    subtotal: Mapped[float | None] = mapped_column(Float)
    tax: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    extraction_confidence: Mapped[str] = mapped_column(Text, default="{}")
    line_items: Mapped[str] = mapped_column(Text, default="[]")
    validation_issues: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
