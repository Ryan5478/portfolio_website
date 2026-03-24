from __future__ import annotations

import os
import sqlite3
import smtplib
from contextlib import closing
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

try:
    import resend
except Exception:  # pragma: no cover
    resend = None


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "Portfolio Contact API")
DB_PATH = BASE_DIR / os.getenv("DATABASE_FILE", "messages.db")
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",") if origin.strip()]
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-this-admin-token")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")

# Resend (best for Render free or other cloud hosts that block SMTP)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "")
RESEND_FROM_NAME = os.getenv("RESEND_FROM_NAME", "Portfolio Website")

# SMTP fallback (good for local development or paid hosts with SMTP access)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME or OWNER_EMAIL)
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

app = FastAPI(title=APP_NAME, version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ContactMessageIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    subject: str = Field(default="", max_length=200)
    message: str = Field(..., min_length=10, max_length=5000)


class ContactMessageOut(BaseModel):
    success: bool
    message: str
    id: int
    created_at: str


class StoredMessage(BaseModel):
    id: int
    name: str
    email: EmailStr
    subject: str
    message: str
    created_at: str


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def root() -> dict[str, str]:
    return {
        "app": APP_NAME,
        "status": "running",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "message": "Backend is running"}


@app.post("/api/contact", response_model=ContactMessageOut, status_code=status.HTTP_201_CREATED)
def create_contact_message(payload: ContactMessageIn) -> ContactMessageOut:
    now = datetime.now(timezone.utc).isoformat()
    new_id = insert_message(payload, now)
    send_owner_notification(payload, new_id, now)

    return ContactMessageOut(
        success=True,
        message="Thanks for reaching out. Your message has been sent successfully.",
        id=new_id,
        created_at=now,
    )


@app.get("/api/messages", response_model=list[StoredMessage])
def list_messages(
    x_admin_token: Annotated[str | None, Header()] = None,
) -> list[StoredMessage]:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, email, subject, message, created_at
            FROM messages
            ORDER BY id DESC
            """
        ).fetchall()

    return [StoredMessage(**dict(row)) for row in rows]


@app.get("/api/messages/{message_id}", response_model=StoredMessage)
def get_message(message_id: int, x_admin_token: Annotated[str | None, Header()] = None) -> StoredMessage:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, name, email, subject, message, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    return StoredMessage(**dict(row))


def init_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def insert_message(payload: ContactMessageIn, created_at: str) -> int:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (name, email, subject, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.email,
                payload.subject.strip(),
                payload.message.strip(),
                created_at,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def send_owner_notification(payload: ContactMessageIn, message_id: int, created_at: str) -> None:
    # Prefer Resend in production/cloud environments
    if RESEND_API_KEY and RESEND_FROM_EMAIL and OWNER_EMAIL and resend is not None:
        send_via_resend(payload, message_id, created_at)
        return

    # Fallback to SMTP for local development or hosts that allow SMTP
    email_ready = all([
        OWNER_EMAIL,
        SMTP_HOST,
        SMTP_USERNAME,
        SMTP_PASSWORD,
        SMTP_FROM_EMAIL,
    ])
    if email_ready:
        send_via_smtp(payload, message_id, created_at)


def send_via_resend(payload: ContactMessageIn, message_id: int, created_at: str) -> None:
    resend.api_key = RESEND_API_KEY

    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#0f172a">
      <h2 style="margin-bottom:12px;">New portfolio contact form submission</h2>
      <p><strong>ID:</strong> {message_id}</p>
      <p><strong>Time:</strong> {created_at}</p>
      <p><strong>Name:</strong> {payload.name}</p>
      <p><strong>Email:</strong> {payload.email}</p>
      <p><strong>Subject:</strong> {payload.subject or 'No subject'}</p>
      <hr style="margin:18px 0;border:none;border-top:1px solid #e2e8f0;" />
      <p style="white-space:pre-wrap;"><strong>Message:</strong><br>{payload.message}</p>
    </div>
    """

    params = {
        "from": f"{RESEND_FROM_NAME} <{RESEND_FROM_EMAIL}>",
        "to": [OWNER_EMAIL],
        "subject": f"New portfolio contact: {payload.subject or 'No subject'}",
        "html": html,
        "text": (
            f"New contact form submission\n\n"
            f"ID: {message_id}\n"
            f"Time: {created_at}\n"
            f"Name: {payload.name}\n"
            f"Email: {payload.email}\n"
            f"Subject: {payload.subject or 'No subject'}\n\n"
            f"Message:\n{payload.message}"
        ),
    }

    try:
        resend.Emails.send(params)
    except Exception as exc:  # pragma: no cover
        print(f"Resend notification skipped: {exc}")


def send_via_smtp(payload: ContactMessageIn, message_id: int, created_at: str) -> None:
    message = EmailMessage()
    message["Subject"] = f"New portfolio contact: {payload.subject or 'No subject'}"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = OWNER_EMAIL
    message["Reply-To"] = payload.email
    message.set_content(
        f"""
New contact form submission

ID: {message_id}
Time: {created_at}
Name: {payload.name}
Email: {payload.email}
Subject: {payload.subject or 'No subject'}

Message:
{payload.message}
        """.strip()
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    except Exception as exc:  # pragma: no cover
        print(f"SMTP notification skipped: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
