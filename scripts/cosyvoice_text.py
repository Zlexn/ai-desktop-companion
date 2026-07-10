from __future__ import annotations

_SENTENCE_ENDINGS = set("。！？!?；;\n")


def split_tts_text(text: str, *, max_chars: int = 40) -> list[str]:
    """Split TTS input into bounded segments without dropping characters."""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    segments: list[str] = []
    current = ""
    for char in normalized:
        current += char
        if char in _SENTENCE_ENDINGS or len(current) >= max_chars:
            segments.extend(_split_oversized(current, max_chars=max_chars))
            current = ""

    if current:
        segments.extend(_split_oversized(current, max_chars=max_chars))
    return [segment for segment in segments if segment]


def _split_oversized(segment: str, *, max_chars: int) -> list[str]:
    return [segment[index:index + max_chars] for index in range(0, len(segment), max_chars)]
