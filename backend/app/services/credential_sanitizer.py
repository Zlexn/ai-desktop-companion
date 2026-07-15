from __future__ import annotations

import re

_REPLACEMENT = "[REDACTED]"
_KEY = r"(?:password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token)"
_QUOTED_KEY = rf"(?:[\"'](?P<quoted_key>{_KEY})[\"']|(?P<bare_key>[A-Za-z0-9_-]*{_KEY}))"
_DOUBLE_QUOTED_VALUE = r'"(?:\\.|[^"\\\r\n])*"'
_SINGLE_QUOTED_VALUE = r"'(?:\\.|[^'\\\r\n])*'"
_CURLY_DOUBLE_VALUE = r"“[^”\r\n]*”"
_CURLY_SINGLE_VALUE = r"‘[^’\r\n]*’"
_UNQUOTED_VALUE = r"[^\s,;。！？、，；：\]\[(){}<>《》“”‘’\"']+"
_BEARER_PATTERN = re.compile(
    rf"(?i)\bBearer\s+(?:{_DOUBLE_QUOTED_VALUE}|{_SINGLE_QUOTED_VALUE}|{_CURLY_DOUBLE_VALUE}|{_CURLY_SINGLE_VALUE}|[A-Za-z0-9._~+\-/]+=*)"
)
_ASSIGNMENT_PATTERN = re.compile(
    rf"(?i){_QUOTED_KEY}\s*[:=]\s*(?:{_DOUBLE_QUOTED_VALUE}|{_SINGLE_QUOTED_VALUE}|{_CURLY_DOUBLE_VALUE}|{_CURLY_SINGLE_VALUE}|{_UNQUOTED_VALUE})"
)
_SECRET_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def sanitize_credentials(text: str) -> tuple[str, int]:
    """Redact obvious credentials as a best-effort boundary, not a DLP guarantee."""
    count = 0

    def replace_bearer(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"Bearer {_REPLACEMENT}"

    def replace_assignment(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        key = match.group("quoted_key") or match.group("bare_key")
        return f"{key}={_REPLACEMENT}"

    def replace_secret(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return _REPLACEMENT

    sanitized = _BEARER_PATTERN.sub(replace_bearer, text)
    sanitized = _ASSIGNMENT_PATTERN.sub(replace_assignment, sanitized)
    sanitized = _SECRET_KEY_PATTERN.sub(replace_secret, sanitized)
    return sanitized.strip(), count
