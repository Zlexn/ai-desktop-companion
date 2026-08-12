import logging
import os
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.services.memory_source_reference import MemorySourceReferenceService


_FIXED_KEY = bytes(range(32))


def test_source_reference_creates_key_atomically_and_is_stable(tmp_path: Path) -> None:
    key_path = tmp_path / "private" / "memory-source.key"

    service = MemorySourceReferenceService.load_or_create(
        key_path,
        references_exist=lambda: False,
        key_factory=lambda: _FIXED_KEY,
    )

    assert key_path.read_bytes() == _FIXED_KEY
    assert service.session_hash("session-1") == service.session_hash("session-1")
    assert service.session_hash("session-1") != service.message_hash("session-1")
    assert service.session_hash("session-1") != service.session_hash("session-2")


def test_source_reference_reuses_existing_key_without_factory(tmp_path: Path) -> None:
    key_path = tmp_path / "memory-source.key"
    key_path.write_bytes(_FIXED_KEY)

    service = MemorySourceReferenceService.load_or_create(
        key_path,
        references_exist=lambda: True,
        key_factory=lambda: pytest.fail("existing key must not be replaced"),
    )

    assert service.message_hash("message-1")
    assert key_path.read_bytes() == _FIXED_KEY


def test_source_reference_missing_key_with_references_fails_closed(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "missing.key"

    with pytest.raises(ValueError, match="source reference key is unavailable"):
        MemorySourceReferenceService.load_or_create(
            key_path,
            references_exist=lambda: True,
            key_factory=lambda: pytest.fail("must not replace a missing key"),
        )

    assert not key_path.exists()


@pytest.mark.parametrize("payload", [b"", b"short", bytes(range(31)), bytes(range(33))])
def test_source_reference_rejects_invalid_key_size(
    tmp_path: Path,
    payload: bytes,
) -> None:
    key_path = tmp_path / "invalid.key"
    key_path.write_bytes(payload)

    with pytest.raises(ValueError, match="exactly 32 bytes"):
        MemorySourceReferenceService.load_or_create(
            key_path,
            references_exist=lambda: False,
        )


def test_source_reference_errors_and_logs_do_not_expose_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key_path = tmp_path / "invalid.key"
    secret = b"private-source-reference-secret"
    key_path.write_bytes(secret)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as exc_info:
            MemorySourceReferenceService.load_or_create(
                key_path,
                references_exist=lambda: False,
            )

    assert secret.decode() not in str(exc_info.value)
    assert secret.decode() not in caplog.text


def test_source_reference_concurrent_creators_observe_complete_winner_key(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "memory-source.key"
    barrier = Barrier(2)
    keys = (_FIXED_KEY, bytes(reversed(range(32))))
    services: list[MemorySourceReferenceService] = []
    errors: list[BaseException] = []

    def create(key: bytes) -> None:
        try:
            barrier.wait()
            services.append(
                MemorySourceReferenceService.load_or_create(
                    key_path,
                    references_exist=lambda: False,
                    key_factory=lambda: key,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=create, args=(key,)) for key in keys]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(services) == 2
    assert len(key_path.read_bytes()) == 32
    assert services[0].session_hash("session-1") == services[1].session_hash(
        "session-1"
    )


def test_source_reference_losing_atomic_publish_uses_winner_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "memory-source.key"
    winner_key = bytes(reversed(range(32)))
    attempted = False
    original_link = os.link

    def racing_link(source, destination, *args, **kwargs):
        nonlocal attempted
        if Path(destination) == key_path and not attempted:
            attempted = True
            key_path.write_bytes(winner_key)
            raise FileExistsError
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    service = MemorySourceReferenceService.load_or_create(
        key_path,
        references_exist=lambda: False,
        key_factory=lambda: _FIXED_KEY,
    )

    assert service.session_hash("session-1") == MemorySourceReferenceService(
        winner_key
    ).session_hash("session-1")
    assert key_path.read_bytes() == winner_key
    assert list(tmp_path.glob("*.tmp")) == []
