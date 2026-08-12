import hashlib
import json


MEMORY_EXTRACTION_PURPOSE = (
    "extract durable memory proposals from the current completed turn"
)
MEMORY_EXTRACTION_DISCLOSURE_VERSION = "memory-extraction-disclosure-v1"
MEMORY_EXTRACTION_DISCLOSED_FIELDS = ("user_message", "assistant_message")


def memory_remote_authority_fingerprint(
    *,
    generation: int,
    purpose: str,
    provider: str,
    disclosure_version: str,
    disclosed_fields: tuple[str, ...],
) -> str:
    material = json.dumps(
        {
            "generation": generation,
            "purpose": purpose,
            "provider": provider,
            "disclosure_version": disclosure_version,
            "disclosed_fields": list(disclosed_fields),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
