import os
import re
import io
import hashlib
from datetime import date, datetime, timedelta
from collections import defaultdict

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, ImageFilter, ImageEnhance

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY", "dev-only-change-me"
)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///smartspend.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv(
    "JWT_SECRET_KEY", "dev-jwt-secret-change-me"
)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
        }
    },
)

db = SQLAlchemy(app)
jwt = JWTManager(app)

CATEGORIES = [
    "Groceries",
    "Utilities",
    "Food",
    "Transport",
    "Shopping",
    "Clothing",
    "Electronics",
    "Healthcare",
    "Entertainment",
    "Education",
    "Rent",
    "Other",
]


# =========================================================
# DATABASE MODELS
# =========================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(
        db.String(180), unique=True, nullable=False, index=True
    )
    password_hash = db.Column(db.String(255), nullable=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    merchant = db.Column(
        db.String(180), nullable=False, default="Unknown merchant"
    )
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(
        db.String(40), nullable=False, default="Other"
    )
    expense_date = db.Column(
        db.Date, nullable=False, default=date.today
    )
    note = db.Column(db.String(500), nullable=True)
    source = db.Column(
        db.String(30), nullable=False, default="manual"
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )

    def to_dict(self):
        return {
            "id": self.id,
            "merchant": self.merchant,
            "amount": round(self.amount, 2),
            "category": self.category,
            "date": self.expense_date.isoformat(),
            "note": self.note or "",
            "source": self.source,
        }


class BillFingerprint(db.Model):
    """Stores fingerprints of receipt images already saved by a user."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )

    file_hash = db.Column(db.String(64), nullable=False)

    expense_id = db.Column(
        db.Integer,
        db.ForeignKey("expense.id"),
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "file_hash",
            name="unique_user_bill_fingerprint",
        ),
    )


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )

    category = db.Column(db.String(40), nullable=False)
    monthly_limit = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "category",
            name="unique_user_category_budget",
        ),
    )


def current_user_id():
    return int(get_jwt_identity())


# =========================================================
# IMAGE PREPROCESSING FOR OCR
# =========================================================

def prepare_images(image_bytes):
    original = Image.open(io.BytesIO(image_bytes))
    original = ImageOps.exif_transpose(original).convert("RGB")

    images = [("original", original)]

    gray = ImageOps.grayscale(original)
    gray = ImageOps.autocontrast(gray)

    if gray.width < 1800:
        scale = min(3, max(1, 1800 / max(gray.width, 1)))

        gray = gray.resize(
            (
                int(gray.width * scale),
                int(gray.height * scale),
            ),
            Image.Resampling.LANCZOS,
        )

    sharp = gray.filter(ImageFilter.SHARPEN)
    sharp = ImageEnhance.Contrast(sharp).enhance(1.6)

    images.append(("enhanced", sharp.convert("RGB")))

    threshold = gray.point(lambda p: 255 if p > 165 else 0)
    images.append(("threshold", threshold.convert("RGB")))

    return images


def call_ocr_space(image, engine="2"):
    api_key = os.getenv("OCR_SPACE_API_KEY", "").strip()

    if not api_key:
        raise ValueError(
            "OCR.Space API key is missing. Add OCR_SPACE_API_KEY "
            "to backend/.env and restart Flask."
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    response = requests.post(
        "https://api.ocr.space/parse/image",
        data={
            "apikey": api_key,
            "language": os.getenv("OCR_SPACE_LANGUAGE", "eng"),
            "isOverlayRequired": "false",
            "OCREngine": engine,
            "scale": "true",
            "detectOrientation": "true",
        },
        files={
            "file": ("receipt.png", buffer, "image/png")
        },
        timeout=60,
    )

    response.raise_for_status()
    payload = response.json()

    if payload.get("IsErroredOnProcessing"):
        raise ValueError(
            str(
                payload.get(
                    "ErrorMessage",
                    "OCR could not read this image.",
                )
            )
        )

    parsed = payload.get("ParsedResults") or []

    text = "\n".join(
        item.get("ParsedText", "") for item in parsed
    ).strip()

    return text


# =========================================================
# AMOUNT EXTRACTION
# =========================================================

def normalize_ocr_text(text):
    text = (text or "").replace("\u20b9", " Rs ")
    text = text.replace("\xa0", " ")
    text = text.replace("—", "-").replace("–", "-")
    return text


def amounts_in(line):
    line = normalize_ocr_text(line)

    pattern = (
        r"(?<![A-Za-z])"
        r"(?:Rs\.?|INR)?\s*"
        r"(?<!\w)"
        r"(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?"
        r"|\d+(?:\.\d{1,2})?)"
        r"(?!\w)"
    )

    results = []

    for match in re.finditer(pattern, line, re.I):
        raw = match.group(1).replace(",", "")

        try:
            value = float(raw)

            if 0 < value <= 10000000:
                results.append(value)

        except ValueError:
            continue

    return results


def parse_amount(text):
    text = normalize_ocr_text(text)

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not lines:
        return None

    def clean_label(value):
        value = value.lower()
        value = re.sub(r"t0tal|totai|tota1", "total", value)
        value = re.sub(r"gr[ae]nd", "grand", value)
        value = re.sub(r"payab[e1]", "payable", value)
        value = re.sub(r"am0unt", "amount", value)
        value = re.sub(r"b[i1]ll", "bill", value)
        return value

    labels = [
        r"\bnet\s+bill\b",
        r"\bnet\s+amount\b",
        r"\bgrand\s+total\b",
        r"\btotal\s+amount\s+due\b",
        r"\btotal\s+amount\s+payable\b",
        r"\bamount\s+payable\b",
        r"\btotal\s+payable\b",
        r"\btotal\s+due\b",
        r"\bbill\s+total\b",
        r"\binvoice\s+total\b",
        r"\btotal\s+invoice\b",
        r"\btotal\s+amount\b",
        r"\bamount\s+due\b",
        r"\bnet\s+payable\b",
        r"\btotal\b",
    ]

    for label in labels:
        for index, line in enumerate(lines):
            cleaned = clean_label(line)

            if re.search(
                r"\b(total\s+gst|gst|cgst|sgst|igst|tax\s+amount)\b",
                cleaned,
            ):
                continue

            match = re.search(label, cleaned)

            if not match:
                continue

            after_label = line[match.end():]
            values = amounts_in(after_label)

            if values:
                return values[-1]

            for next_index in range(
                index + 1, min(index + 3, len(lines))
            ):
                next_line = lines[next_index]

                if re.search(
                    r"\b(gst|cgst|sgst|igst|tax)\b",
                    clean_label(next_line),
                ):
                    continue

                values = amounts_in(next_line)

                if values:
                    return values[-1]

    for index, line in enumerate(lines):
        if re.search(
            r"\b(cash|paid|amount paid|upi|card payment)\b",
            line,
            re.I,
        ):
            values = amounts_in(line)

            if values:
                return values[-1]

            for next_line in lines[index + 1:index + 3]:
                values = amounts_in(next_line)

                if values:
                    return values[-1]

    utility_labels = [
        r"\bbill\s+amount\b",
        r"\bbill\s+aft\s+sub\b",
        r"\bamount\s+after\s+subsidy\b",
        r"\bpayable\s+amount\b",
    ]

    for label in utility_labels:
        for index, line in enumerate(lines):
            cleaned = clean_label(line)
            match = re.search(label, cleaned)

            if not match:
                continue

            values = amounts_in(line[match.end():])

            if values:
                return values[-1]

            if index + 1 < len(lines):
                values = amounts_in(lines[index + 1])

                if values:
                    return values[-1]

    for line in reversed(lines):
        cleaned = clean_label(line)

        if re.search(r"\btotal\b", cleaned) and not re.search(
            r"\b(gst|cgst|sgst|igst|tax)\b", cleaned
        ):
            values = amounts_in(line)

            if values:
                return values[-1]

    return None


# =========================================================
# CATEGORY DETECTION
# =========================================================

def categorize(text):
    s = re.sub(r"\s+", " ", (text or "").lower())
    compact = re.sub(r"[^a-z0-9]+", " ", s).strip()

    utility_patterns = [
        r"\belectricity\b",
        r"\belectricity bill\b",
        r"\belectric bill\b",
        r"\belectric shop\b",
        r"\beb bill\b",
        r"\btneb\b",
        r"\btangedco\b",
        r"\bconsumer number\b",
        r"\bconsumer no\b",
        r"\bservice number\b",
        r"\bunits consumed\b",
        r"\bkwh\b",
        r"\benergy chrg\b",
        r"\benergy charge\b",
        r"\bfixed chrg\b",
        r"\bcust chrg\b",
        r"\bpower distribution\b",
        r"\bnet bill\b.*\bdue date\b",
        r"\bwater bill\b",
        r"\bwater charges?\b",
        r"\bmunicipal water\b",
        r"\bgas bill\b",
        r"\bpiped gas\b",
        r"\bbroadband bill\b",
        r"\binternet bill\b",
        r"\bmobile bill\b",
        r"\btelephone bill\b",
    ]

    if any(
        re.search(pattern, s, re.I)
        for pattern in utility_patterns
    ):
        return "Utilities"

    rules = [
        ("Electronics", [
            "laptop", "computer", "keyboard", "mouse", "monitor",
            "usb cable", "usb hub", "charger", "headphone", "earphone",
            "electronics", "ssd", "printer", "hard disk", "webcam",
            "hdmi cable", "router", "memory card", "pendrive",
            "power bank", "mobile phone", "smartphone",
        ]),
        ("Clothing", [
            "shirt", "shirts", "t-shirt", "pants", "trousers", "dress",
            "blazer", "jeans", "apparel", "garment", "clothing",
            "fashion wear", "cotton", "skirt", "kurti", "saree", "jacket",
        ]),
        ("Food", [
            "coffee", "tea", "restaurant", "cafe", "café", "swiggy",
            "zomato", "food", "bakery", "pizza", "meal", "snack",
            "beverage", "canteen", "dining", "espresso", "latte",
            "cappuccino", "sandwich", "burger", "coffee/tea",
        ]),
        ("Groceries", [
            "grocery", "groceries", "supermarket", "provision store",
            "vegetable", "vegetables", "fruit", "fruits", "rice", "milk",
            "bread", "bigbasket", "reliance fresh", "dmart",
        ]),
        ("Transport", [
            "petrol", "diesel", "fuel", "uber", "ola", "bus fare",
            "train ticket", "metro", "parking", "fastag", "toll",
            "indian oil", "bharat petroleum",
        ]),
        ("Healthcare", [
            "pharmacy", "medical", "hospital", "clinic", "medicine",
            "diagnostic", "chemist", "prescription",
        ]),
        ("Entertainment", [
            "movie", "cinema", "netflix", "spotify", "theatre",
            "game subscription", "concert",
        ]),
        ("Education", [
            "college fee", "school fee", "tuition", "course",
            "exam fee", "university",
        ]),
        ("Rent", [
            "house rent", "monthly rent", "rental payment",
        ]),
        ("Shopping", [
            "amazon", "flipkart", "mall", "shopping",
        ]),
    ]

    for category, keywords in rules:
        for keyword in keywords:
            if re.search(
                r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])",
                compact,
            ):
                return category

    return "Other"


# =========================================================
# DATE AND MERCHANT EXTRACTION
# =========================================================

def parse_date(text):
    text = (text or "").replace(",", " ")

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    formats = [
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%m-%Y", "%d/%m/%Y",
        "%d-%m-%y", "%d/%m/%y",
        "%m-%d-%Y", "%m/%d/%Y",
        "%m-%d-%y", "%m/%d/%y",
        "%d %b %Y", "%d %B %Y",
        "%b %d %Y", "%B %d %Y",
    ]

    preferred = [
        line for line in lines
        if re.search(
            r"\b(bill date|invoice date|receipt date|date)\b",
            line,
            re.I,
        )
        and not re.search(
            r"\b(due date|disc date|expiry date)\b",
            line,
            re.I,
        )
    ]

    candidates = preferred + [
        line for line in lines if line not in preferred
    ]

    patterns = [
        r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",
        r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
        r"\b([A-Za-z]{3,9}\s+\d{1,2}\s+\d{4})\b",
    ]

    for line in candidates:
        for pattern in patterns:
            for match in re.finditer(pattern, line):
                value = match.group(1).replace("/", "-")

                for fmt in formats:
                    try:
                        parsed = datetime.strptime(
                            value, fmt
                        ).date()

                        if (
                            date(2000, 1, 1)
                            <= parsed
                            <= date.today() + timedelta(days=1)
                        ):
                            return parsed

                    except ValueError:
                        continue

    return None


def parse_merchant(text):
    lines = [
        re.sub(r"\s+", " ", line).strip(" :-|")
        for line in (text or "").splitlines()
    ]

    lines = [line for line in lines if line]

    for i in range(min(6, len(lines) - 1)):
        if (
            lines[i].upper() == "V"
            and lines[i + 1].upper() == "MART"
        ):
            return "V Mart"

    ignored = (
        "invoice", "receipt", "tax invoice", "bill no", "bill date",
        "date:", "phone", "gstin", "fssai", "retail invoice",
        "address", "cashier", "description", "qty", "quantity",
        "amount", "rate", "particulars", "energy chrg", "fixed chrg",
        "cust chrg", "net bill", "due date", "disc date", "bill aft sub",
        "govt subsidy", "original for recipient", "sample test bill",
    )

    for line in lines[:12]:
        if len(line) < 3:
            continue

        if re.search(r"\d{5,}", line):
            continue

        if any(word in line.lower() for word in ignored):
            continue

        if not re.search(r"[A-Za-z]{3,}", line):
            continue

        return line[:180].title()

    return "Unknown merchant"


# =========================================================
# OCR STRATEGY
# =========================================================

def run_ocr(image_bytes):
    api_key = os.getenv("OCR_SPACE_API_KEY", "").strip()

    if api_key:
        image_variants = prepare_images(image_bytes)
        results = []
        errors = []

        try:
            text = call_ocr_space(image_variants[0][1], "2")

            if text:
                results.append(text)

        except Exception as exc:
            errors.append(str(exc))

        best = max(results, key=len, default="")

        if (
            not best
            or parse_amount(best) is None
            or len(best) < 40
        ):
            for _, image in image_variants[1:2]:
                try:
                    text = call_ocr_space(image, "2")

                    if text:
                        results.append(text)

                except Exception as exc:
                    errors.append(str(exc))

        if not results or all(
            parse_amount(result) is None for result in results
        ):
            try:
                text = call_ocr_space(image_variants[1][1], "1")

                if text:
                    results.append(text)

            except Exception as exc:
                errors.append(str(exc))

        if results:
            best = max(
                results,
                key=lambda value: (
                    100 if parse_amount(value) is not None else 0,
                    len(value),
                ),
            )

            return best, "OCR.Space API"

        raise ValueError(
            "OCR.Space could not read this image. Check your API key, "
            "internet connection, or try a clearer photo. "
            + (errors[-1] if errors else "")
        )

    try:
        import pytesseract

        images = prepare_images(image_bytes)

        local_results = [
            pytesseract.image_to_string(image)
            for _, image in images[:2]
        ]

        best = max(
            local_results,
            key=lambda value: (
                100 if parse_amount(value) is not None else 0,
                len(value),
            ),
        )

        if best.strip():
            return best, "Local Tesseract"

    except Exception:
        pass

    raise ValueError(
        "OCR is not configured. Add OCR_SPACE_API_KEY to backend/.env "
        "or install Tesseract OCR and pytesseract."
    )


# =========================================================
# HEALTH AND AUTHENTICATION ROUTES
# =========================================================

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "SmartSpend AI API",
    })


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or len(password) < 8:
        return jsonify({
            "error": (
                "Enter your name, a valid email and a password "
                "of at least 8 characters."
            )
        }), 400

    if User.query.filter_by(email=email).first():
        return jsonify({
            "error": "An account with this email already exists."
        }), 409

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
    )

    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))

    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        },
    }), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(
        user.password_hash, password
    ):
        return jsonify({
            "error": "Incorrect email or password."
        }), 401

    token = create_access_token(identity=str(user.id))

    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        },
    })


@app.get("/api/auth/me")
@jwt_required()
def me():
    user = db.session.get(User, current_user_id())

    if not user:
        return jsonify({"error": "User not found."}), 404

    return jsonify({
        "id": user.id,
        "name": user.name,
        "email": user.email,
    })


# =========================================================
# EXPENSE ROUTES
# =========================================================

@app.get("/api/expenses")
@jwt_required()
def get_expenses():
    query = Expense.query.filter_by(
        user_id=current_user_id()
    )

    start = request.args.get("start")
    end = request.args.get("end")
    category = request.args.get("category")

    try:
        if start:
            query = query.filter(
                Expense.expense_date >= date.fromisoformat(start)
            )

        if end:
            query = query.filter(
                Expense.expense_date <= date.fromisoformat(end)
            )

    except ValueError:
        return jsonify({
            "error": "Dates must use YYYY-MM-DD format."
        }), 400

    if category:
        query = query.filter_by(category=category)

    expenses = query.order_by(
        Expense.expense_date.desc(),
        Expense.id.desc(),
    ).all()

    return jsonify([expense.to_dict() for expense in expenses])


@app.post("/api/expenses")
@jwt_required()
def create_expense():
    data = request.get_json(silent=True) or {}
    uid = current_user_id()

    try:
        amount = float(data.get("amount"))

        expense_date = date.fromisoformat(
            data.get("date") or date.today().isoformat()
        )

    except (TypeError, ValueError):
        return jsonify({
            "error": "Enter a valid amount and date."
        }), 400

    if amount <= 0 or amount > 100000000:
        return jsonify({
            "error": (
                "Amount must be greater than zero and "
                "within the supported limit."
            )
        }), 400

    source = (
        data.get("source")
        if data.get("source") in ("manual", "ocr")
        else "manual"
    )

    file_hash = data.get("file_hash") if source == "ocr" else None

    # Validate the hash before using it in a database query.
    if file_hash is not None:
        if (
            not isinstance(file_hash, str)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", file_hash)
        ):
            return jsonify({
                "error": "Invalid bill fingerprint. Please scan again."
            }), 400

        existing_fingerprint = BillFingerprint.query.filter_by(
            user_id=uid,
            file_hash=file_hash,
        ).first()

        if existing_fingerprint:
            return jsonify({
                "error": "This bill image has already been saved.",
                "duplicate": True,
                "duplicate_expense_id": (
                    existing_fingerprint.expense_id
                ),
            }), 409

    merchant = (
        data.get("merchant") or "Unknown merchant"
    ).strip()[:180]

    note = (data.get("note") or "")[:500]
    category = data.get("category")

    if category not in CATEGORIES:
        category = categorize(merchant + " " + note)

    expense = Expense(
        user_id=uid,
        merchant=merchant or "Unknown merchant",
        amount=amount,
        category=category,
        expense_date=expense_date,
        note=note,
        source=source,
    )

    try:
        db.session.add(expense)
        db.session.flush()

        if file_hash:
            fingerprint = BillFingerprint(
                user_id=uid,
                file_hash=file_hash,
                expense_id=expense.id,
            )

            db.session.add(fingerprint)

        db.session.commit()

    except Exception:
        db.session.rollback()
        app.logger.exception("Expense save failed")

        return jsonify({
            "error": (
                "Could not save the expense. "
                "Please try again."
            )
        }), 500

    return jsonify(expense.to_dict()), 201


@app.put("/api/expenses/<int:expense_id>")
@jwt_required()
def update_expense(expense_id):
    expense = Expense.query.filter_by(
        id=expense_id,
        user_id=current_user_id(),
    ).first_or_404()

    data = request.get_json(silent=True) or {}

    if "amount" in data:
        try:
            expense.amount = float(data["amount"])

        except (ValueError, TypeError):
            return jsonify({"error": "Invalid amount."}), 400

        if expense.amount <= 0:
            return jsonify({
                "error": "Amount must be greater than zero."
            }), 400

    if "date" in data:
        try:
            expense.expense_date = date.fromisoformat(data["date"])

        except (ValueError, TypeError):
            return jsonify({"error": "Invalid date."}), 400

    if "merchant" in data:
        expense.merchant = (
            data.get("merchant") or "Unknown merchant"
        ).strip()[:180]

    if data.get("category") in CATEGORIES:
        expense.category = data["category"]

    if "note" in data:
        expense.note = (data.get("note") or "")[:500]

    db.session.commit()

    return jsonify(expense.to_dict())


@app.delete("/api/expenses/<int:expense_id>")
@jwt_required()
def delete_expense(expense_id):
    expense = Expense.query.filter_by(
        id=expense_id,
        user_id=current_user_id(),
    ).first_or_404()

    db.session.delete(expense)
    db.session.commit()

    return jsonify({"message": "Expense deleted."})


# =========================================================
# OCR ROUTE WITH DUPLICATE IMAGE DETECTION
# =========================================================

@app.post("/api/ocr")
@jwt_required()
def ocr_bill():
    if "file" not in request.files:
        return jsonify({
            "error": "Choose an image file first."
        }), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({
            "error": "Choose an image file first."
        }), 400

    ext = os.path.splitext(
        secure_filename(file.filename)
    )[1].lower()

    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        return jsonify({
            "error": "Upload a JPG, PNG, WEBP or BMP image."
        }), 400

    raw = file.read()

    if not raw or len(raw) > 8 * 1024 * 1024:
        return jsonify({
            "error": "Image is empty or larger than 8 MB."
        }), 400

    # Calculate SHA-256 fingerprint for the uploaded image.
    file_hash = hashlib.sha256(raw).hexdigest()
    uid = current_user_id()

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()

        existing_fingerprint = BillFingerprint.query.filter_by(
            user_id=uid,
            file_hash=file_hash,
        ).first()

        text, provider = run_ocr(raw)

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    except requests.RequestException:
        return jsonify({
            "error": (
                "OCR provider request failed. "
                "Check internet and API key."
            )
        }), 502

    except Exception:
        app.logger.exception("OCR processing failed")

        return jsonify({
            "error": (
                "Could not read this image. "
                "Try a clearer, well-lit photo."
            )
        }), 422

    amount = parse_amount(text)
    merchant = parse_merchant(text)
    category = categorize(text + " " + merchant)
    parsed_date = parse_date(text)

    return jsonify({
        "merchant": merchant,
        "amount": amount,
        "date": (
            parsed_date.isoformat()
            if parsed_date else None
        ),
        "category": category,
        "raw_text": text[:12000],
        "provider": provider,
        "file_hash": file_hash,
        "duplicate": existing_fingerprint is not None,
        "duplicate_expense_id": (
            existing_fingerprint.expense_id
            if existing_fingerprint else None
        ),
        "message": (
            "This exact image has already been saved. "
            "Do not save it again."
            if existing_fingerprint
            else
            "Please verify the amount, date and category before saving. "
            "If the amount is null, enter the printed total manually."
        ),
    })


# =========================================================
# ANALYTICS: WEEKLY / MONTHLY TOTALS AND BUDGET ALERTS
# =========================================================

@app.get("/api/analytics")
@jwt_required()
def analytics():
    period = request.args.get("period", "month")
    today = date.today()

    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = today
    else:
        period = "month"
        start = today.replace(day=1)
        end = today

    expenses = Expense.query.filter(
        Expense.user_id == current_user_id(),
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ).order_by(Expense.expense_date.asc()).all()

    total = sum(expense.amount for expense in expenses)

    by_category = defaultdict(float)
    by_day = defaultdict(float)

    for expense in expenses:
        by_category[expense.category] += expense.amount

        key = expense.expense_date.isoformat()
        by_day[key] += expense.amount

    category_data = [
        {
            "category": key,
            "amount": round(value, 2),
        }
        for key, value in sorted(
            by_category.items(),
            key=lambda item: -item[1],
        )
    ]

    daily_data = [
        {
            "date": key,
            "amount": round(value, 2),
        }
        for key, value in sorted(by_day.items())
    ]

    budgets = Budget.query.filter_by(
        user_id=current_user_id()
    ).all()

    budget_alerts = []

    for budget in budgets:
        spent = by_category.get(budget.category, 0.0)
        limit = budget.monthly_limit

        if limit > 0 and spent >= limit * 0.8:
            budget_alerts.append({
                "category": budget.category,
                "limit": round(limit, 2),
                "spent": round(spent, 2),
                "percentage": round(spent / limit * 100),
                "level": (
                    "over" if spent > limit
                    else "reached" if spent >= limit
                    else "warning"
                ),
            })

    if period == "week":
        previous_start = start - timedelta(days=7)
    else:
        previous_start = (
            start - timedelta(days=1)
        ).replace(day=1)

    previous_end = start - timedelta(days=1)

    previous_expenses = Expense.query.filter(
        Expense.user_id == current_user_id(),
        Expense.expense_date >= previous_start,
        Expense.expense_date <= previous_end,
    ).all()

    previous_total = sum(
        expense.amount for expense in previous_expenses
    )

    change_pct = (
        round(
            (total - previous_total) / previous_total * 100,
            1,
        )
        if previous_total else None
    )

    return jsonify({
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total": round(total, 2),
        "transaction_count": len(expenses),
        "average": (
            round(total / len(expenses), 2)
            if expenses else 0
        ),
        "previous_total": round(previous_total, 2),
        "change_percent": change_pct,
        "categories": category_data,
        "daily": daily_data,
        "alerts": budget_alerts,
        "category_options": CATEGORIES,
    })


# =========================================================
# BUDGET ROUTES
# =========================================================

@app.get("/api/budgets")
@jwt_required()
def get_budgets():
    uid = current_user_id()
    budgets = Budget.query.filter_by(user_id=uid).all()

    today = date.today()
    month_start = today.replace(day=1)

    expenses = Expense.query.filter(
        Expense.user_id == uid,
        Expense.expense_date >= month_start,
        Expense.expense_date <= today,
    ).all()

    spent = defaultdict(float)

    for expense in expenses:
        spent[expense.category] += expense.amount

    return jsonify([
        {
            "id": budget.id,
            "category": budget.category,
            "monthly_limit": budget.monthly_limit,
            "spent": round(spent[budget.category], 2),
            "percentage": (
                round(
                    spent[budget.category]
                    / budget.monthly_limit * 100
                )
                if budget.monthly_limit else 0
            ),
        }
        for budget in budgets
    ])


@app.post("/api/budgets")
@jwt_required()
def save_budget():
    data = request.get_json(silent=True) or {}

    category = data.get("category")

    try:
        limit = float(data.get("monthly_limit"))

    except (ValueError, TypeError):
        return jsonify({
            "error": "Enter a valid monthly limit."
        }), 400

    if category not in CATEGORIES or limit <= 0:
        return jsonify({
            "error": (
                "Choose a valid category and a limit "
                "greater than zero."
            )
        }), 400

    uid = current_user_id()

    budget = Budget.query.filter_by(
        user_id=uid,
        category=category,
    ).first()

    if budget:
        budget.monthly_limit = limit

    else:
        budget = Budget(
            user_id=uid,
            category=category,
            monthly_limit=limit,
        )

        db.session.add(budget)

    db.session.commit()

    return jsonify({
        "id": budget.id,
        "category": budget.category,
        "monthly_limit": budget.monthly_limit,
    })


@app.delete("/api/budgets/<int:budget_id>")
@jwt_required()
def delete_budget(budget_id):
    budget = Budget.query.filter_by(
        id=budget_id,
        user_id=current_user_id(),
    ).first_or_404()

    db.session.delete(budget)
    db.session.commit()

    return jsonify({"message": "Budget deleted."})


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

with app.app_context():
    db.create_all()


# =========================================================
# START FLASK SERVER
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "true").lower() == "true",
        port=5000,
    )