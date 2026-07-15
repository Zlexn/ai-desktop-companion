from __future__ import annotations

from app.services.credential_sanitizer import sanitize_credentials


def sanitize_summary_text(text: str) -> str:
    sanitized, _redaction_count = sanitize_credentials(text)
    return sanitized
