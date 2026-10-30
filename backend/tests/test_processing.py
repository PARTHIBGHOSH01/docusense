from app.processing import detect_document_type, extract_fields, extract_line_items, extraction_confidence, validate

def test_extracts_invoice_fields_and_totals():
    text = "Acme Supplies\nInvoice Number: AC-1042\nInvoice Date: 2026-01-10\nSubtotal $100.00\nTax $8.00\nTotal $108.00"
    fields = extract_fields(text)
    assert fields["vendor"] == "Acme Supplies"
    assert fields["invoice_number"] == "AC-1042"
    assert fields["total"] == 108
    assert validate(fields) == []

def test_flags_missing_data_and_mismatched_totals():
    issues = validate({"vendor": None, "invoice_number": None, "invoice_date": None,
                       "subtotal": 100, "tax": 5, "total": 120})
    assert "Missing vendor" in issues
    assert "Missing invoice number" in issues
    assert "Subtotal plus tax does not match total" in issues

def test_extracts_amounts_on_following_lines_and_ignores_invoice_reference():
    text = """NORTHSTAR OFFICE SUPPLIES
Invoice Number: NS-2026-1042
Invoice Date: 2026-10-20
Subtotal
$600.00
Tax
$48.00
Total
$648.00
Please include the invoice number with your payment."""
    fields = extract_fields(text)
    assert fields["invoice_number"] == "NS-2026-1042"
    assert fields["subtotal"] == 600
    assert fields["tax"] == 48
    assert fields["total"] == 648
    assert validate(fields) == []

def test_receipt_classification_and_line_item_rows():
    text = """RECEIPT
Riverbend Market
Receipt Number: R-2048
Date: 2026-10-21
DESCRIPTION
QTY
UNIT PRICE
AMOUNT
Coffee beans
2
$12.00
$24.00
Subtotal
$24.00
Tax
$1.92
Total
$25.92"""
    fields = extract_fields(text)
    items = extract_line_items(text)
    assert detect_document_type(text) == "receipt"
    assert fields["invoice_number"] == "R-2048"
    assert items == [{"description": "Coffee beans", "quantity": 2.0, "unit_price": 12.0, "amount": 24.0}]
    assert validate(fields, "receipt") == []
    assert extraction_confidence(text, fields, items)["total"] == "high"

def test_unrecognized_document_can_be_saved_as_other():
    assert detect_document_type("Employee handbook\nVacation policy") == "other"
    assert validate({}, "other") == []
