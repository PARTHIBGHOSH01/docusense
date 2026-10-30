import re
from pathlib import Path

MONEY = r"(?:\$|USD\s*)?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))"
MONEY_VALUE = re.compile(MONEY, re.I)

def extract_text(path: Path, content_type: str) -> str:
    """Extract PDF text; use Tesseract for images/scanned PDFs when installed."""
    if content_type == "application/pdf":
        try:
            import fitz
            doc = fitz.open(path)
            pages = [page.get_text("text") for page in doc]
            text = "\n".join(pages).strip()
            if text:
                return text[:100_000]
            return _ocr_pdf(path)
        except ImportError:
            return _ocr_pdf(path)
        except Exception as exc:
            raise ValueError("The PDF could not be read") from exc
    try:
        import pytesseract
        from PIL import Image
        with Image.open(path) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("The image is too large to process")
            image.load()
            return pytesseract.image_to_string(image)[:100_000]
    except ImportError:
        return ""
    except Exception as exc:
        try:
            import pytesseract
            if isinstance(exc, pytesseract.TesseractNotFoundError):
                return ""
        except ImportError:
            return ""
        raise ValueError("The image could not be read. Check that it is a valid PNG or JPEG.") from exc

def _ocr_pdf(path: Path) -> str:
    try:
        import fitz, pytesseract
        from PIL import Image
        import io
        doc = fitz.open(path)
        parts = []
        for page in doc[:10]:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            parts.append(pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png")))))
        return "\n".join(parts)[:100_000]
    except ImportError:
        return ""
    except Exception:
        return ""

def extract_fields(text: str) -> dict:
    fields = {"vendor": None, "invoice_number": None, "invoice_date": None, "due_date": None,
              "currency": "USD", "subtotal": None, "tax": None, "total": None}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        m = re.match(r"^(?:invoice|receipt)\s*(?:no\.?|number|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{1,})\s*$", line, re.I)
        if m:
            fields["invoice_number"] = m.group(1)
        if fields["invoice_date"] is None and re.search(r"invoice\s*date|\bdate\b", line, re.I):
            m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", line)
            if m: fields["invoice_date"] = m.group(1)
        if re.search(r"due\s*date", line, re.I):
            m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", line)
            if m: fields["due_date"] = m.group(1)
    if lines and not re.search(r"invoice|bill to|statement", lines[0], re.I):
        fields["vendor"] = lines[0][:255]
    for key, labels in (("subtotal", r"subtotal|sub-total"), ("tax", r"tax|vat|gst"), ("total", r"(?:grand\s+)?total|amount\s+due|balance\s+due")):
        for index in range(len(lines) - 1, -1, -1):
            line = lines[index]
            if not re.search(rf"^\s*(?:{labels})\b", line, re.I):
                continue
            candidates = [line, *lines[index + 1:index + 3]]
            for candidate in candidates:
                nums = re.findall(MONEY, candidate, re.I)
                if nums:
                    try: fields[key] = float(nums[-1].replace(",", ""))
                    except ValueError: pass
                    break
                if candidate != line and re.search(r"subtotal|sub-total|tax|vat|gst|total|amount due|balance due", candidate, re.I):
                    break
            if fields[key] is not None:
                break
    if "€" in text: fields["currency"] = "EUR"
    elif "£" in text: fields["currency"] = "GBP"
    elif "₹" in text: fields["currency"] = "INR"
    elif "CAD" in text: fields["currency"] = "CAD"
    elif "AUD" in text: fields["currency"] = "AUD"
    return fields

def detect_document_type(text: str) -> str:
    heading = "\n".join(text.splitlines()[:12]).lower()
    if re.search(r"\b(receipt|point of sale|cash receipt)\b", heading):
        return "receipt"
    if re.search(r"\binvoice\b|invoice\s*(?:no\.?|number|#)", heading):
        return "invoice"
    return "other"

def extract_line_items(text: str) -> list[dict]:
    """Extract obvious table rows; keep only rows with a description and amount."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = next((i for i, line in enumerate(lines) if "description" in line.lower() and
                   any(word in " ".join(lines[i:i + 5]).lower() for word in ("qty", "quantity")) and
                   any(word in " ".join(lines[i:i + 5]).lower() for word in ("amount", "price"))), -1)
    start = header + 1 if header >= 0 else 0
    items = []
    i = start
    while i < len(lines):
        line = lines[i]
        if re.match(r"^(subtotal|sub-total|tax|vat|gst|grand total|total|amount due|balance due)\b", line, re.I):
            break
        # Common text-PDF layout: description, quantity, unit price, line total on separate lines.
        if (i + 3 < len(lines) and not MONEY_VALUE.search(line) and len(line) > 2 and
                re.fullmatch(r"\d+(?:\.\d+)?", lines[i + 1]) and
                MONEY_VALUE.search(lines[i + 2]) and MONEY_VALUE.search(lines[i + 3])):
            price = float(MONEY_VALUE.search(lines[i + 2]).group(1).replace(",", ""))
            amount = float(MONEY_VALUE.search(lines[i + 3]).group(1).replace(",", ""))
            items.append({"description": line, "quantity": float(lines[i + 1]), "unit_price": price, "amount": amount})
            i += 4
            continue
        # Inline rows such as "Design service 2 $45.00 $90.00" or pipe-delimited tables.
        values = MONEY_VALUE.findall(line)
        if values:
            first_money = MONEY_VALUE.search(line).start()
            prefix = line[:first_money].strip(" |\t")
            qty_match = re.search(r"\s(\d+(?:\.\d+)?)\s*$", prefix)
            description = prefix[:qty_match.start()].strip(" |\t") if qty_match else prefix
            if len(description) > 2 and not re.search(r"\b(subtotal|tax|vat|gst|total|amount due|balance due)\b", description, re.I):
                amounts = [float(value.replace(",", "")) for value in values]
                items.append({"description": description, "quantity": float(qty_match.group(1)) if qty_match else None,
                              "unit_price": amounts[-2] if len(amounts) > 1 else None, "amount": amounts[-1]})
        i += 1
    return items[:100]

def extraction_confidence(text: str, fields: dict, line_items: list[dict]) -> dict[str, str]:
    """Heuristic signal labels, not calibrated probabilities."""
    result = {key: "unavailable" for key in (
        "vendor", "invoice_number", "invoice_date", "due_date", "subtotal", "tax", "total", "line_items")}
    if fields.get("vendor"):
        result["vendor"] = "medium"
    for key, pattern in (("invoice_number", r"^(?:invoice|receipt)\s*(?:no\.?|number|#)"),
                         ("invoice_date", r"^(?:invoice\s*)?date\b"), ("due_date", r"^due\s*date\b")):
        if fields.get(key):
            result[key] = "high" if any(re.search(pattern, line, re.I) for line in text.splitlines()) else "medium"
    lines = [line.strip() for line in text.splitlines()]
    for key, pattern in (("subtotal", r"^\s*(?:subtotal|sub-total)\b"),
                         ("tax", r"^\s*(?:tax|vat|gst)\b"),
                         ("total", r"^\s*(?:(?:grand\s+)?total|amount\s+due|balance\s+due)\b")):
        if fields.get(key) is not None:
            result[key] = "high" if any(re.search(pattern, line, re.I) for line in lines) else "medium"
    if line_items:
        result["line_items"] = "medium"
    return result

def validate(fields: dict, document_type: str = "invoice") -> list[str]:
    issues = []
    required = ("vendor", "invoice_number", "invoice_date", "total") if document_type == "invoice" else (
        ("vendor", "invoice_date", "total") if document_type == "receipt" else ())
    for key in required:
        if fields.get(key) in (None, ""):
            issues.append(f"Missing {key.replace('_', ' ')}")
    sub, tax, total = fields.get("subtotal"), fields.get("tax"), fields.get("total")
    if sub is not None and tax is not None and total is not None and abs(sub + tax - total) > 0.02:
        issues.append("Subtotal plus tax does not match total")
    if any(fields.get(k) is not None and fields[k] < 0 for k in ("subtotal", "tax", "total")):
        issues.append("Invoice amounts cannot be negative")
    return issues
