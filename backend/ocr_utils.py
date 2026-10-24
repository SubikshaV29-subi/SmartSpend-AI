
import re
import os
import hashlib
import requests

from datetime import datetime, date
from decimal import Decimal, InvalidOperation


# --------------------------------------------------
# 1. CLEAN OCR TEXT
# --------------------------------------------------

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\r", "\n")
    text = text.replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


# --------------------------------------------------
# 2. EXTRACT AMOUNT
# --------------------------------------------------

def parse_amount(value):
    """Convert OCR amount text into a positive decimal."""

    if not value:
        return None

    value = value.strip()
    value = value.replace(",", "")
    value = value.replace("₹", "")
    value = value.replace("Rs.", "")
    value = value.replace("Rs", "")
    value = value.replace("INR", "")
    value = value.replace(" ", "")

    # Correct common OCR mistakes only in numeric values.
    value = value.replace("O", "0").replace("o", "0")

    match = re.fullmatch(r"(\d+(?:\.\d{1,2})?)", value)

    if not match:
        return None

    try:
        amount = Decimal(match.group(1))
        if amount <= 0 or amount > Decimal("100000000"):
            return None
        return amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def extract_amount(text):
    """
    Prefer explicit payable/total labels.
    Do not simply choose the largest number on the bill.
    """

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Strong total labels are checked before generic total labels.
    patterns = [
        r"(?:net\s+bill|net\s+amount\s+payable|"
        r"total\s+amount\s+(?:due|payable)|amount\s+payable|"
        r"balance\s+due|bill\s+amount|grand\s+total|"
        r"total\s+due|net\s+payable|invoice\s+total)"
        r"\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*"
        r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    ]

    for pattern in patterns:
        for line in reversed(lines):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                amount = parse_amount(match.group(1))
                if amount is not None:
                    return amount, "label_match"

    # Electricity bills often print "NET BILL" on one line
    # and the payable amount on the next line.
    for index, line in enumerate(lines):
        if re.search(
            r"\b(net\s+bill|grand\s+total|amount\s+payable|"
            r"total\s+amount\s+due|bill\s+amount)\b",
            line,
            re.IGNORECASE
        ):
            for following in lines[index:index + 3]:
                candidates = re.findall(
                    r"(?<![A-Za-z])(?:₹|Rs\.?\s*)?"
                    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
                    following,
                    re.IGNORECASE
                )

                for candidate in candidates:
                    amount = parse_amount(candidate)
                    if amount is not None:
                        return amount, "near_total_label"

    # Fallback: only accept an amount on a line explicitly
    # labelled TOTAL, and not a subtotal or tax-only line.
    for line in reversed(lines):
        if re.search(r"\b(subtotal|tax total|total gst)\b", line, re.I):
            continue

        if re.search(r"\btotal\b", line, re.I):
            values = re.findall(
                r"(?<![A-Za-z])(?:₹|Rs\.?\s*)?"
                r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
                line,
                re.IGNORECASE
            )

            for candidate in reversed(values):
                amount = parse_amount(candidate)
                if amount is not None:
                    return amount, "total_line"

    return None, "not_found"


# --------------------------------------------------
# 3. EXTRACT DATE
# --------------------------------------------------

def extract_date(text):
    patterns = [
        (r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", "%Y-%m-%d"),
        (r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", None),
        (r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", None),
    ]

    # Search labelled dates first.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    labelled_lines = [
        line for line in lines
        if re.search(
            r"\b(bill date|invoice date|receipt date|date)\b",
            line,
            re.IGNORECASE
        )
    ]

    for line in labelled_lines + lines:
        for pattern, fmt in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if not match:
                continue

            try:
                if fmt:
                    parsed = datetime.strptime(match.group(0), fmt).date()
                elif pattern == patterns[1][0]:
                    first, second, year = map(int, match.groups())

                    # Indian receipts commonly use DD-MM-YYYY.
                    parsed = date(year, second, first)

                else:
                    parsed = datetime.strptime(
                        match.group(0), "%d %B %Y"
                    ).date() if len(match.group(2)) > 3 else datetime.strptime(
                        match.group(0), "%d %b %Y"
                    ).date()

                # Reject implausible dates rather than silently
                # treating them as today's date.
                if date(2000, 1, 1) <= parsed <= date.today():
                    return parsed.isoformat()

            except ValueError:
                continue

    return None


# --------------------------------------------------
# 4. EXTRACT MERCHANT
# --------------------------------------------------

def extract_merchant(text):
    ignored = re.compile(
        r"\b(invoice|receipt|cash bill|tax invoice|"
        r"bill date|invoice date|gstin|gst no|"
        r"phone|mobile|address|customer|description|"
        r"quantity|qty|rate|amount|total|subtotal|"
        r"cash|card|upi|thank you|original for recipient)\b",
        re.IGNORECASE
    )

    for line in text.splitlines()[:12]:
        line = re.sub(r"\s+", " ", line).strip()
        line = line.strip(" :|-.")

        if len(line) < 3 or len(line) > 65:
            continue

        if ignored.search(line):
            continue

        if not re.search(r"[A-Za-z]", line):
            continue

        if re.fullmatch(r"[\d\s./:#-]+", line):
            continue

        return line.title()

    return None


# --------------------------------------------------
# 5. AUTOMATIC CATEGORY
# --------------------------------------------------

CATEGORY_KEYWORDS = {
    "Groceries": [
        "grocery", "groceries", "supermarket", "vegetables",
        "vegetable", "fruits", "fruit", "rice", "milk",
        "provision store", "kirana", "grocery store"
    ],
    "Food & Dining": [
        "restaurant", "cafe", "coffee", "tea", "hotel",
        "bakery", "pizza", "burger", "food", "swiggy",
        "zomato", "dining", "beverages"
    ],
    "Utilities": [
        "electricity", "electric bill", "eb bill",
        "tneb", "tangedco", "power supply", "net bill",
        "water bill", "water charges", "gas bill",
        "utility bill", "consumer number", "energy charge"
    ],
    "Transport": [
        "petrol", "diesel", "fuel", "parking", "toll",
        "bus ticket", "train ticket", "metro", "uber",
        "ola", "transport", "auto fare"
    ],
    "Shopping": [
        "shopping", "clothing", "shirt", "trousers",
        "dress", "fashion", "garments", "footwear",
        "mall", "superstore"
    ],
    "Healthcare": [
        "pharmacy", "medical store", "hospital",
        "clinic", "medicine", "medicines", "diagnostic",
        "laboratory", "doctor"
    ],
    "Electronics": [
        "electronics", "mobile phone", "laptop",
        "computer", "charger", "headphones",
        "electrical shop", "appliance"
    ],
}


def categorize_expense(text, merchant=None):
    searchable = f"{merchant or ''}\n{text}".lower()

    # Check specific electricity-related terms first.
    if any(word in searchable for word in [
        "electricity bill", "electricity board", "tneb",
        "tangedco", "energy charge", "consumer number",
        "net bill", "power supply"
    ]):
        return "Utilities"

    scores = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(
            1 for keyword in keywords
            if keyword in searchable
        )

    best_category = max(scores, key=scores.get)

    if scores[best_category] == 0:
        return "Other"

    return best_category


# --------------------------------------------------
# 6. OCR.SPACE API
# --------------------------------------------------

def run_ocr(image_bytes):
    api_key = os.getenv("OCR_SPACE_API_KEY")

    if not api_key:
        raise ValueError(
            "OCR_SPACE_API_KEY is missing from backend/.env"
        )

    response = requests.post(
        "https://api.ocr.space/parse/image",
        data={
            "apikey": api_key,
            "language": os.getenv("OCR_SPACE_LANGUAGE", "eng"),
            "isOverlayRequired": "false",
            "detectOrientation": "true",
            "scale": "true",
            "isTable": "true",
            "OCREngine": "2",
        },
        files={
            "file": ("bill.jpg", image_bytes, "application/octet-stream")
        },
        timeout=60
    )

    response.raise_for_status()
    result = response.json()

    if result.get("IsErroredOnProcessing"):
        errors = result.get("ErrorMessage", "OCR processing failed")
        raise ValueError(str(errors))

    pages = result.get("ParsedResults") or []

    extracted = "\n".join(
        page.get("ParsedText", "")
        for page in pages
    )

    extracted = clean_text(extracted)

    if not extracted:
        raise ValueError(
            "No readable text found. Try a clearer image."
        )

    return extracted


# --------------------------------------------------
# 7. PROCESS BILL
# --------------------------------------------------

def process_bill(image_bytes):
    text = run_ocr(image_bytes)

    merchant = extract_merchant(text)
    amount, amount_method = extract_amount(text)
    bill_date = extract_date(text)
    category = categorize_expense(text, merchant)

    # A stable hash for identifying the exact uploaded file.
    file_hash = hashlib.sha256(image_bytes).hexdigest()

    return {
        "merchant": merchant or "",
        "amount": float(amount) if amount is not None else None,
        "date": bill_date or "",
        "category": category,
        "extracted_text": text,
        "amount_method": amount_method,
        "needs_review": (
            amount is None or
            bill_date is None or
            merchant is None
        ),
        "file_hash": file_hash,
    }
