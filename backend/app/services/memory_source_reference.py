from __future__ import annotations

from collections.abc import Callable
import hashlib
import hmac
import os
from pathlib import Path
from secrets import token_bytes, token_hex


_KEY_SIZE = 32


class MemorySourceReferenceService:
    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_SIZE:
            raise ValueError("memory source reference key must be exactly 32 bytes")
        self._key = bytes(key)

    @classmethod
    def load_or_create(
        cls,
        path: Path,
        *,
        references_exist: Callable[[], bool],
        key_factory: Callable[[], bytes] = lambda: token_bytes(_KEY_SIZE),
    ) -> MemorySourceReferenceService:
        key_path = Path(path)
        try:
            key = key_path.read_bytes()
        except FileNotFoundError:
            if references_exist():
                raise ValueError("memory source reference key is unavailable") from None
            key = key_factory()
            if len(key) != _KEY_SIZE:
                raise ValueError(
                    "memory source reference key must be exactly 32 bytes"
                )
            key_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = key_path.with_name(
                f".{key_path.name}.{token_hex(16)}.tmp"
            )
            try:
                with temporary_path.open(mode="xb") as key_file:
                    key_file.write(key)
                    key_file.flush()
                    os.fsync(key_file.fileno())
                try:
                    os.link(temporary_path, key_path)
                except FileExistsError:
                    key = key_path.read_bytes()
                else:
                    try:
                        key_path.chmod(0o600)
                    except OSError:
                        pass
            finally:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
        return cls(key)

    def session_hash(self, session_id: str) -> str:
        return self._digest("session", session_id)

    def message_hash(self, message_id: str) -> str:
        return self._digest("message", message_id)

    def _digest(self, kind: str, source_id: str) -> str:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source reference id must be a non-empty string")
        material = f"{kind}:{source_id}".encode("utf-8")
        return hmac.new(self._key, material, hashlib.sha256).hexdigest()
