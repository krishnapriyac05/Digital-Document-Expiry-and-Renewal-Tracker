"""Local web application for tracking document expiry and renewals."""

from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape as xml_escape
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

from flask import Flask, jsonify, make_response, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "documents.db")))
# Read a simple local .env file for database configuration; never overwrite an
# environment variable explicitly set by VS Code or the shell.
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PORT = int(os.environ.get("PORT", "5051"))
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:5500")
SERVE_FRONTEND = os.environ.get("SERVE_FRONTEND", "false").lower() in {"1", "true", "yes"}
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
)
app.json.sort_keys = False


class MySQLConnection:
    """Small DB-API adapter so the app's parameterized queries work on MySQL."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        cursor = self.connection.cursor()
        cursor.execute(re.sub(r"\?", "%s", sql), params)
        return cursor


class PostgresCursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def rowcount(self):
        return self.cursor.rowcount


class PostgresConnection:
    """Adapt PostgreSQL cursors and placeholders to the app's DB interface."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        statement = re.sub(r"\?", "%s", sql.strip().rstrip(";"))
        is_insert = bool(re.match(r"INSERT\s+INTO\b", statement, re.IGNORECASE))
        if is_insert and not re.search(r"\bRETURNING\b", statement, re.IGNORECASE):
            statement += " RETURNING id"
        cursor = self.connection.cursor()
        cursor.execute(statement, params)
        lastrowid = None
        if is_insert:
            row = cursor.fetchone()
            lastrowid = row["id"]
        return PostgresCursor(cursor, lastrowid)


def is_mysql():
    return DATABASE_URL.startswith(("mysql://", "mysql+pymysql://"))


def is_postgres():
    return DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))


@contextmanager
def connect():
    if DATABASE_URL and not (is_postgres() or is_mysql()):
        raise RuntimeError("DATABASE_URL must use PostgreSQL or MySQL; refusing to fall back to temporary SQLite storage.")
    if is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL mode needs psycopg. Install requirements.txt.") from exc
        database_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        raw = psycopg.connect(database_url, row_factory=dict_row)
        db = PostgresConnection(raw)
        try:
            yield db
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
        return

    if is_mysql():
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise RuntimeError("MySQL mode needs PyMySQL. Run: python -m pip install -r requirements.txt") from exc
        parsed = urlparse(DATABASE_URL.replace("mysql+pymysql://", "mysql://", 1))
        raw = pymysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=parsed.path.lstrip("/"),
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )
        db = MySQLConnection(raw)
        try:
            yield db
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
        return

    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    try:
        yield raw
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def initialize(seed_empty: bool = True) -> None:
    with connect() as db:
        if is_postgres():
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                name VARCHAR(80) NOT NULL,
                email VARCHAR(254) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                id BIGSERIAL PRIMARY KEY,
                owner_id BIGINT NULL,
                name VARCHAR(100) NOT NULL,
                doc_type VARCHAR(60) NOT NULL,
                issue_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS renewals (
                id BIGSERIAL PRIMARY KEY,
                owner_id BIGINT NULL,
                document_id BIGINT NULL,
                document_name VARCHAR(100) NOT NULL DEFAULT '',
                previous_issue_date TEXT NOT NULL,
                previous_expiry_date TEXT NOT NULL,
                new_issue_date TEXT NOT NULL,
                new_expiry_date TEXT NOT NULL,
                renewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
            )""")
            for table in ("documents", "renewals"):
                db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS owner_id BIGINT NULL")
        elif is_mysql():
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(80) NOT NULL,
                email VARCHAR(254) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                owner_id INT NULL,
                name VARCHAR(100) NOT NULL,
                doc_type VARCHAR(60) NOT NULL,
                issue_date DATE NOT NULL,
                expiry_date DATE NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            db.execute("""CREATE TABLE IF NOT EXISTS renewals (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                owner_id INT NULL,
                document_id INT NULL,
                document_name VARCHAR(100) NOT NULL DEFAULT '',
                previous_issue_date DATE NOT NULL,
                previous_expiry_date DATE NOT NULL,
                new_issue_date DATE NOT NULL,
                new_expiry_date DATE NOT NULL,
                renewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_renewal_document (document_id),
                INDEX idx_renewal_time (renewed_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            for table in ("documents", "renewals"):
                if db.execute(f"SHOW COLUMNS FROM {table} LIKE 'owner_id'").fetchone() is None:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INT NULL")
        else:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                name TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                issue_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS renewals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                document_id INTEGER,
                document_name TEXT NOT NULL DEFAULT '',
                previous_issue_date TEXT NOT NULL,
                previous_expiry_date TEXT NOT NULL,
                new_issue_date TEXT NOT NULL,
                new_expiry_date TEXT NOT NULL,
                renewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
            for table in ("documents", "renewals"):
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
                if "owner_id" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER")
        # Seed only an empty workspace, using fictional sample records to make
        # the dashboard and expiry windows immediately demonstrable.
        users_total = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        if seed_empty and users_total == 0 and db.execute("SELECT COUNT(*) AS total FROM documents").fetchone()["total"] == 0:
            today = date.today()
            samples = [
                ("City Driving Licence", "Driving licence", today - timedelta(days=730), today + timedelta(days=6)),
                ("Northstar Vehicle Cover", "Vehicle insurance", today - timedelta(days=365), today + timedelta(days=13)),
                ("Travel Passport", "Passport", today - timedelta(days=1460), today + timedelta(days=215)),
                ("Cloud Security Certificate", "Software certification", today - timedelta(days=365), today - timedelta(days=3)),
            ]
            for name, doc_type, issued, expires in samples:
                db.execute("INSERT INTO documents(name, doc_type, issue_date, expiry_date) VALUES (?, ?, ?, ?)",
                           (name, doc_type, issued.isoformat(), expires.isoformat()))


def parse_iso(value: object, label: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date.") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be a valid date.")
    return parsed


def as_iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def serialize(row) -> dict:
    item = dict(row)
    item["issue_date"] = as_iso(item["issue_date"])
    item["expiry_date"] = as_iso(item["expiry_date"])
    expiry = date.fromisoformat(item["expiry_date"])
    days = (expiry - date.today()).days
    item["days_remaining"] = days
    item["status"] = "Expired" if days < 0 else "Expiring Soon" if days <= 30 else "Active"
    return item


def documents() -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM documents WHERE owner_id=? ORDER BY expiry_date, id", (session["user_id"],)).fetchall()
    return [serialize(row) for row in rows]


def report_documents(report_type: str) -> list[dict]:
    rows = documents()
    if report_type == "active":
        return [row for row in rows if row["status"] == "Active"]
    if report_type == "expired":
        return [row for row in rows if row["status"] == "Expired"]
    if report_type in {"7", "15", "30"}:
        days = int(report_type)
        return [row for row in rows if 0 <= row["days_remaining"] <= days]
    return rows


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@app.get("/")
def backend_home():
    if SERVE_FRONTEND:
        return render_template("index.html", asset_version="render-production-v1")
    return jsonify({"service": "Document Tracker API", "health": "/api/health", "frontend": FRONTEND_ORIGIN})


@app.get("/config.js")
def frontend_config():
    # A blank base makes the hosted frontend use its own origin, including its
    # HTTPS scheme, so browser cookies and API requests stay same-origin.
    api_base = "" if SERVE_FRONTEND else f"http://127.0.0.1:{PORT}"
    response = make_response(f"window.DOC_TRACKER_API_BASE = {api_base!r};\n")
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.after_request
def add_frontend_cors_headers(response):
    if request.headers.get("Origin") == FRONTEND_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = FRONTEND_ORIGIN
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Vary"] = "Origin"
    return response


PUBLIC_API_ENDPOINTS = {"register_account", "login_account", "logout_account", "current_session", "health"}


@app.before_request
def require_login_for_workspace_api():
    if request.method == "OPTIONS":
        return "", 204
    if request.path.startswith("/api/") and request.endpoint not in PUBLIC_API_ENDPOINTS and not session.get("user_id"):
        return error("Please log in to open your document workspace.", 401)


@app.post("/api/register")
def register_account():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or len(name) > 80:
        return error("Enter a name between 2 and 80 characters.")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        return error("Enter a valid email address.")
    if len(password) < 8:
        return error("Choose a password with at least 8 characters.")
    with connect() as db:
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return error("An account with this email already exists. Please log in.", 409)
        first_account = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"] == 0
        cursor = db.execute(
            "INSERT INTO users(name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        user_id = cursor.lastrowid
        if first_account:
            # Preserve the existing single-user workspace when the first account is created.
            db.execute("UPDATE documents SET owner_id=? WHERE owner_id IS NULL", (user_id,))
            db.execute("UPDATE renewals SET owner_id=? WHERE owner_id IS NULL", (user_id,))
    # Registration creates the account but leaves the user logged out so they
    # can explicitly sign in using the login form.
    session.clear()
    return jsonify({"registered": True, "user": {"id": user_id, "name": name, "email": email}}), 201


@app.post("/api/login")
def login_account():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return error("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return jsonify({"authenticated": True, "user": {"id": user["id"], "name": user["name"], "email": user["email"]}})


@app.post("/api/logout")
def logout_account():
    session.clear()
    return jsonify({"authenticated": False})


@app.get("/api/session")
def current_session():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "user": {"id": user_id, "name": session.get("user_name", "")}})


@app.get("/api/documents")
def list_documents():
    return jsonify(documents())


@app.get("/api/health")
def health():
    owner_id = session.get("user_id")
    with connect() as db:
        if owner_id:
            total = db.execute("SELECT COUNT(*) AS total FROM documents WHERE owner_id=?", (owner_id,)).fetchone()["total"]
            renewal_total = db.execute("SELECT COUNT(*) AS total FROM renewals WHERE owner_id=?", (owner_id,)).fetchone()["total"]
        else:
            total = renewal_total = 0
    result = {
        "status": "ok",
        "storage": "PostgreSQL" if is_postgres() else "MySQL" if is_mysql() else "SQLite",
        "document_count": total,
        "renewal_count": renewal_total,
    }
    if not is_mysql() and not is_postgres():
        result["database_path"] = str(DB_PATH)
        result["configuration_note"] = "DATABASE_URL is not configured; using the local SQLite database."
    return jsonify(result)


@app.get("/api/documents/search")
def search_documents():
    term = request.args.get("q", "").strip().casefold()
    items = documents()
    if term:
        items = [item for item in items if term in item["name"].casefold() or term in item["doc_type"].casefold()]
    return jsonify({"query": term, "count": len(items), "items": items})


@app.post("/api/demo-data")
def add_demo_data():
    today = date.today()
    # Fictional dashboard fixtures. Top up each status group to the example
    # totals (15 active, 3 expired, 7 expiring soon), without replacing any
    # documents the user has already saved.
    candidates = {
        "Active": [
            ("Demo Passport - Northwind", "Passport", 900),
            ("Demo Driving Licence - Cedar", "Driving licence", 540),
            ("Demo Vehicle Cover - Juniper", "Vehicle insurance", 365),
            ("Demo Cloud Security Certificate", "Software certification", 180),
            ("Demo Travel Document - Harbor", "Travel document", 730),
            ("Demo Health Cover - Meadow", "Health insurance", 120),
            ("Demo Professional Certificate - Summit", "Software certification", 240),
            ("Demo Home Safety Certificate", "Certificate", 1500),
            ("Demo Membership - Bluebird", "Membership", 365),
            ("Demo Education Certificate - Maple", "Education", 1200),
            ("Demo Vehicle Registration - Lakeside", "Vehicle registration", 90),
            ("Demo Travel Insurance - Orchard", "Travel insurance", 600),
            ("Demo First Aid Certificate - Pine", "Software certification", 45),
            ("Demo Work Permit - Alder", "Work permit", 720),
            ("Demo Equipment Warranty - Coral", "Warranty", 540),
            ("Demo Professional Licence - Robin", "Professional licence", 800),
        ],
        "Expired": [
            ("Demo Expired Safety Certificate", "Certificate", -12),
            ("Demo Expired Travel Cover", "Travel insurance", -2),
            ("Demo Expired Vehicle Registration - Bay", "Vehicle registration", -24),
        ],
        "Expiring Soon": [
            ("Demo Licence Renewal - Willow", "Driving licence", 3),
            ("Demo Vehicle Policy - Elm", "Vehicle insurance", 11),
            ("Demo Training Certificate - Birch", "Software certification", 18),
            ("Demo Passport Renewal - Aspen", "Passport", 26),
            ("Demo Equipment Permit - Fern", "Permit", 8),
            ("Demo Health Policy - Cove", "Health insurance", 29),
            ("Demo Warranty Renewal - Stone", "Warranty", 14),
        ],
    }
    targets = {"Active": 15, "Expired": 3, "Expiring Soon": 7}
    current = documents()
    counts = {status: sum(item["status"] == status for item in current) for status in targets}
    inserted = 0
    with connect() as db:
        for status, records in candidates.items():
            needed = max(0, targets[status] - counts[status])
            for name, doc_type, expiry_offset in records:
                if needed == 0:
                    break
                exists = db.execute("SELECT 1 FROM documents WHERE owner_id=? AND name=? AND doc_type=?", (session["user_id"], name, doc_type)).fetchone()
                if exists:
                    continue
                expires = today + timedelta(days=expiry_offset)
                issued = min(today - timedelta(days=365), expires - timedelta(days=90))
                db.execute("INSERT INTO documents(owner_id, name, doc_type, issue_date, expiry_date) VALUES (?, ?, ?, ?, ?)",
                           (session["user_id"], name, doc_type, issued.isoformat(), expires.isoformat()))
                inserted += 1
                needed -= 1
    renewal_rows_added = add_demo_renewal_history()
    return jsonify({"added": inserted, "renewals_added": renewal_rows_added})


def add_demo_renewal_history() -> int:
    """Create fictional, internally consistent history for example records."""
    example_names = (
        "Sample Driving Licence",
        "Sample Vehicle Insurance",
        "Sample Passport",
        "Sample Software Certification",
        "vehicle insurance",
    )
    added = 0
    with connect() as db:
        for name in example_names:
            document = db.execute("SELECT * FROM documents WHERE owner_id=? AND name=? ORDER BY id LIMIT 1", (session["user_id"], name)).fetchone()
            if document is None:
                continue
            existing = db.execute("SELECT 1 FROM renewals WHERE owner_id=? AND document_id=? LIMIT 1", (session["user_id"], document["id"])).fetchone()
            if existing:
                continue
            new_issue = date.fromisoformat(as_iso(document["issue_date"]))
            new_expiry = date.fromisoformat(as_iso(document["expiry_date"]))
            previous_issue = new_issue - timedelta(days=730)
            previous_expiry = new_issue - timedelta(days=1)
            db.execute(
                "INSERT INTO renewals(owner_id, document_id, document_name, previous_issue_date, previous_expiry_date, new_issue_date, new_expiry_date, renewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session["user_id"], document["id"], name, previous_issue.isoformat(), previous_expiry.isoformat(),
                 new_issue.isoformat(), new_expiry.isoformat(), f"{new_issue.isoformat()} 09:00:00"),
            )
            added += 1
    return added


@app.post("/api/documents")
def add_document():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    doc_type = str(data.get("doc_type", "")).strip()
    if not name or not doc_type:
        return error("Document name and type are required.")
    if len(name) > 100 or len(doc_type) > 60:
        return error("Document name must be 100 characters or fewer and type 60 or fewer.")
    try:
        issue = parse_iso(data.get("issue_date"), "Issue date")
        expiry = parse_iso(data.get("expiry_date"), "Expiry date")
    except ValueError as exc:
        return error(str(exc))
    if expiry < issue:
        return error("Expiry date cannot be earlier than issue date.")
    with connect() as db:
        cursor = db.execute("INSERT INTO documents(owner_id, name, doc_type, issue_date, expiry_date) VALUES (?, ?, ?, ?, ?)",
                             (session["user_id"], name, doc_type, issue.isoformat(), expiry.isoformat()))
        row = db.execute("SELECT * FROM documents WHERE id=? AND owner_id=?", (cursor.lastrowid, session["user_id"])).fetchone()
    return jsonify(serialize(row)), 201


@app.put("/api/documents/<int:document_id>")
def update_document(document_id: int):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    doc_type = str(data.get("doc_type", "")).strip()
    if not name or not doc_type:
        return error("Document name and type are required.")
    try:
        issue = parse_iso(data.get("issue_date"), "Issue date")
        expiry = parse_iso(data.get("expiry_date"), "Expiry date")
    except ValueError as exc:
        return error(str(exc))
    if expiry < issue:
        return error("Expiry date cannot be earlier than issue date.")
    with connect() as db:
        cursor = db.execute("UPDATE documents SET name=?, doc_type=?, issue_date=?, expiry_date=? WHERE id=? AND owner_id=?",
                             (name, doc_type, issue.isoformat(), expiry.isoformat(), document_id, session["user_id"]))
        if cursor.rowcount == 0:
            return error("Document not found.", 404)
        row = db.execute("SELECT * FROM documents WHERE id=? AND owner_id=?", (document_id, session["user_id"])).fetchone()
    return jsonify(serialize(row))


@app.delete("/api/documents/<int:document_id>")
def delete_document(document_id: int):
    with connect() as db:
        row = db.execute("SELECT name FROM documents WHERE id=? AND owner_id=?", (document_id, session["user_id"])).fetchone()
        if row is None:
            return error("Document not found.", 404)
        # Keep renewal history readable even after its document is removed.
        db.execute("UPDATE renewals SET document_id=NULL, document_name=? WHERE document_id=? AND owner_id=?", (row["name"], document_id, session["user_id"]))
        db.execute("DELETE FROM documents WHERE id=? AND owner_id=?", (document_id, session["user_id"]))
    return jsonify({"success": True})


@app.post("/api/documents/<int:document_id>/renew")
def renew_document(document_id: int):
    data = request.get_json(silent=True) or {}
    try:
        issue = parse_iso(data.get("issue_date"), "New issue date")
        expiry = parse_iso(data.get("expiry_date"), "New expiry date")
    except ValueError as exc:
        return error(str(exc))
    if expiry < issue:
        return error("Expiry date cannot be earlier than issue date.")
    with connect() as db:
        old = db.execute("SELECT * FROM documents WHERE id=? AND owner_id=?", (document_id, session["user_id"])).fetchone()
        if old is None:
            return error("Document not found.", 404)
        db.execute("INSERT INTO renewals(owner_id, document_id, document_name, previous_issue_date, previous_expiry_date, new_issue_date, new_expiry_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (session["user_id"], document_id, old["name"], old["issue_date"], old["expiry_date"], issue.isoformat(), expiry.isoformat()))
        db.execute("UPDATE documents SET issue_date=?, expiry_date=? WHERE id=? AND owner_id=?",
                   (issue.isoformat(), expiry.isoformat(), document_id, session["user_id"]))
        updated = db.execute("SELECT * FROM documents WHERE id=? AND owner_id=?", (document_id, session["user_id"])).fetchone()
    return jsonify(serialize(updated))


@app.get("/api/renewals")
def renewal_history():
    with connect() as db:
        rows = db.execute("SELECT r.*, COALESCE(d.name, r.document_name) AS document_name FROM renewals r LEFT JOIN documents d ON d.id=r.document_id WHERE r.owner_id=? ORDER BY r.renewed_at DESC, r.id DESC", (session["user_id"],)).fetchall()
    return jsonify([normalize_renewal(row) for row in rows])


def normalize_renewal(row) -> dict:
    item = dict(row)
    for key in ("previous_issue_date", "previous_expiry_date", "new_issue_date", "new_expiry_date"):
        item[key] = as_iso(item[key])
    item["renewed_at"] = as_iso(item["renewed_at"])
    return item


@app.get("/api/reports/<report_type>")
def get_report(report_type: str):
    if report_type not in {"all", "active", "expired", "7", "15", "30", "renewals"}:
        return error("Unknown report. Choose all, active, expired, 7, 15, 30, or renewals.", 404)
    if report_type == "renewals":
        with connect() as db:
            rows = db.execute("SELECT r.*, COALESCE(d.name, r.document_name) AS document_name FROM renewals r LEFT JOIN documents d ON d.id=r.document_id WHERE r.owner_id=? ORDER BY r.renewed_at DESC, r.id DESC", (session["user_id"],)).fetchall()
        return jsonify({"type": "renewals", "count": len(rows), "items": [normalize_renewal(row) for row in rows]})
    items = report_documents(report_type)
    return jsonify({"type": report_type, "count": len(items), "items": items})


@app.get("/api/report.csv")
def report_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Document", "Type", "Issue date", "Expiry date", "Status", "Days remaining"])
    report_type = request.args.get("type", "all")
    if report_type not in {"all", "active", "expired", "7", "15", "30"}:
        return error("Unknown status report type.", 404)
    for item in report_documents(report_type):
        writer.writerow([item["id"], item["name"], item["doc_type"], item["issue_date"], item["expiry_date"], item["status"], item["days_remaining"]])
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=document-status-report.csv"
    return response


def excel_column(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def xlsx_response(title: str, headers: list[str], rows: list[list[object]], widths: list[int], filename: str):
    """Build a small formatted XLSX using only Python's standard library."""
    all_rows = [headers, *rows]
    last_col = excel_column(len(headers))
    last_row = len(all_rows)
    worksheet_rows = []
    for row_number, values in enumerate(all_rows, start=1):
        cells = []
        for col_number, value in enumerate(values, start=1):
            cell_ref = f"{excel_column(col_number)}{row_number}"
            if row_number > 1 and isinstance(value, datetime):
                value = value.date()
            if row_number > 1 and isinstance(value, date):
                serial = (value - date(1899, 12, 30)).days
                cells.append(f'<c r="{cell_ref}" s="2"><v>{serial}</v></c>')
            elif row_number > 1 and isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
            else:
                style = ' s="1"' if row_number == 1 else ""
                text_value = xml_escape(str(value if value is not None else ""))
                cells.append(f'<c r="{cell_ref}" t="inlineStr"{style}><is><t xml:space="preserve">{text_value}</t></is></c>')
        height = ' ht="26" customHeight="1"' if row_number == 1 else ""
        worksheet_rows.append(f'<row r="{row_number}"{height}>{"".join(cells)}</row>')
    cols_xml = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, start=1))
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{last_col}{last_row}"/><sheetViews><sheetView showGridLines="0" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{cols_xml}</cols><sheetData>{"".join(worksheet_rows)}</sheetData>'
        f'<autoFilter ref="A1:{last_col}{last_row}"/></worksheet>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd mmm yyyy"/></numFmts>'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF10345C"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{xml_escape(title[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as workbook_zip:
        workbook_zip.writestr("[Content_Types].xml", content_types)
        workbook_zip.writestr("_rels/.rels", root_rels)
        workbook_zip.writestr("xl/workbook.xml", workbook)
        workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        workbook_zip.writestr("xl/styles.xml", styles)
        workbook_zip.writestr("xl/worksheets/sheet1.xml", worksheet)
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@app.get("/api/report.xlsx")
def report_xlsx():
    report_type = request.args.get("type", "all")
    if report_type not in {"all", "active", "expired", "7", "15", "30"}:
        return error("Unknown status report type.", 404)
    rows = [[
        f"DOC{item['id']:03d}", item["name"], item["doc_type"], date.fromisoformat(item["issue_date"]),
        date.fromisoformat(item["expiry_date"]), item["status"], item["days_remaining"],
    ] for item in report_documents(report_type)]
    return xlsx_response("Document status", ["ID", "Document", "Type", "Issue date", "Expiry date", "Status", "Days remaining"], rows,
                         [12, 34, 27, 18, 18, 18, 18], "document-status-report.xlsx")


@app.get("/api/renewals.xlsx")
def renewals_xlsx():
    with connect() as db:
        rows = db.execute("SELECT r.*, COALESCE(d.name, r.document_name) AS document_name FROM renewals r LEFT JOIN documents d ON d.id=r.document_id WHERE r.owner_id=? ORDER BY r.renewed_at DESC, r.id DESC", (session["user_id"],)).fetchall()
    data = [[row["document_name"], date.fromisoformat(as_iso(row["previous_issue_date"])),
             date.fromisoformat(as_iso(row["previous_expiry_date"])), date.fromisoformat(as_iso(row["new_issue_date"])),
             date.fromisoformat(as_iso(row["new_expiry_date"])), date.fromisoformat(as_iso(row["renewed_at"])[:10])]
            for row in rows]
    return xlsx_response("Renewal history", ["Document", "Previous issue", "Previous expiry", "New issue date", "New expiry date", "Renewed on"],
                         data, [34, 18, 18, 18, 18, 18], "renewal-history-report.xlsx")


@app.get("/api/renewals.csv")
def renewals_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Document", "Previous issue date", "Previous expiry date", "New issue date", "New expiry date", "Renewed at"])
    with connect() as db:
        rows = db.execute("SELECT COALESCE(d.name, r.document_name) AS document_name, r.previous_issue_date, r.previous_expiry_date, r.new_issue_date, r.new_expiry_date, r.renewed_at FROM renewals r LEFT JOIN documents d ON d.id=r.document_id WHERE r.owner_id=? ORDER BY r.renewed_at DESC, r.id DESC", (session["user_id"],)).fetchall()
    for row in rows:
        writer.writerow([row["document_name"], row["previous_issue_date"], row["previous_expiry_date"], row["new_issue_date"], row["new_expiry_date"], row["renewed_at"]])
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=renewal-history-report.csv"
    return response


if __name__ == "__main__":
    initialize()
    if is_postgres():
        print("Document Tracker storage: configured PostgreSQL database")
    elif is_mysql():
        print("Document Tracker storage: configured MySQL database")
    else:
        print(f"Document Tracker storage: SQLite at {DB_PATH}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
