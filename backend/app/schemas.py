from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class InvoiceUpdate(BaseModel):
    document_type: str = Field("invoice", pattern="^(invoice|receipt|other)$")
    vendor: str | None = Field(None, max_length=255)
    invoice_number: str | None = Field(None, max_length=120)
    invoice_date: str | None = Field(None, max_length=40)
    due_date: str | None = Field(None, max_length=40)
    currency: str = Field("USD", pattern="^[A-Z]{3}$")
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    status: str = Field("needs_review", pattern="^(needs_review|approved)$")

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    content_type: str
    status: str
    document_type: str
    duplicate_of_id: int | None
    vendor: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    currency: str
    subtotal: float | None
    tax: float | None
    total: float | None
    extracted_text: str
    extraction_confidence: dict[str, str]
    line_items: list[dict[str, Any]]
    validation_issues: list[str]
    created_at: datetime
    updated_at: datetime
