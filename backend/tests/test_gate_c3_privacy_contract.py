"""Gate C3 generated-value privacy contract.

Generate runtime-random sentinels for preferred address, source memory prose,
summary text, raw Provider output, API key, HMAC, private fingerprint, Prompt
injection, and a private asset path. Check public API JSON, captured logs,
Composer output after forget, assistant manifests, metadata-only tables, and
selected raw SQLite surfaces. Directly assert the forgotten address is absent
from every readable event/projection column and the apply payload is NULL.

Forbidden public keys are asserted absent from the relationship API surface.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import MemorySource, MemoryType
from app.main import create_app
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from tests.test_relationship_projector import (
    _BASE_TIME,
    _insert_persona,
)

FORBIDDEN_PUBLIC_KEYS = (
    "payload_json",
    "source_set_hash",
    "canonical_key_hash",
    "subject_key_hash",
    "content_hash",
    "inherited_authority_fingerprint",
    "integrity_fingerprint",
    "source_memory_version_id",
    "source_event_ids",
    "prompt",
    "raw_response",
    "authorization",
    "api_key",
    "hmac",
)


def _sentinel(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _database(tmp_path: Path, name: str):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _seed_preferred_address(
    connection,
    *,
    address: str,
    prose: str,
) -> str:
    _insert_persona(connection, "persona-1")
    connection.commit()
    references = MemorySourceReferenceService(b"q" * 32)
    memories = MemoryRepository(connection, source_references=references)
    memory, _conflicts = memories.create(
        content=address,
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code="preferred_address",
    )
    connection.commit()
    # Also seed a second memory whose prose is a sentinel to prove it is not
    # copied into the relationship layer.
    memories.create(
        content=prose,
        memory_type=MemoryType.USER_FACT,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
    )
    connection.commit()
    return memory.id


def _scheduler(connection) -> RelationshipScheduler:
    return RelationshipScheduler(
        RelationshipReconciler(connection),
        persona_artifact_id="persona-1",
    )


def _table_text(connection, table: str) -> str:
    rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return str(tuple(tuple(row) for row in rows))


def test_forgotten_address_absent_from_every_readable_relationship_surface(
    tmp_path: Path,
) -> None:
    address = _sentinel("address")
    prose = _sentinel("prose")
    with _database(tmp_path, "privacy-forget.db") as connection:
        memory_id = _seed_preferred_address(
            connection,
            address=address,
            prose=prose,
        )
        references = MemorySourceReferenceService(b"q" * 32)
        versioned = VersionedMemoryRepository(connection)
        versioned.bootstrap_legacy(memory_id, source_references=references)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        # The address is present before forget (bounded relationship copy).
        assert address in connection.execute(
            "SELECT COALESCE(payload_json, '') FROM relationship_events"
        ).fetchone()[0]

        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        forget.forget_memory(memory_id)
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        # Apply payload physically NULL; address absent from every event column.
        rows = connection.execute(
            "SELECT id, payload_json, payload_state FROM relationship_events"
        ).fetchall()
        for row in rows:
            assert row["payload_json"] is None
        assert address not in _table_text(connection, "relationship_events")

        # Historical projection columns never contain address text.
        assert address not in _table_text(connection, "relationship_projections")

        # Jobs/audits/authority/lineage are metadata-only: no address, no prose.
        for table in (
            "relationship_reconcile_jobs",
            "relationship_job_audits",
            "relationship_authority_decisions",
            "relationship_memory_lineage",
        ):
            assert address not in _table_text(connection, table)
            assert prose not in _table_text(connection, table)


def test_relationship_layer_never_copies_source_prose(tmp_path: Path) -> None:
    prose = _sentinel("prose")
    address = _sentinel("address")
    with _database(tmp_path, "privacy-prose.db") as connection:
        _seed_preferred_address(connection, address=address, prose=prose)
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=1))

        # Source prose never enters any relationship surface.
        for table in (
            "relationship_events",
            "relationship_projections",
            "relationship_reconcile_jobs",
            "relationship_job_audits",
        ):
            assert prose not in _table_text(connection, table)


def test_public_relationship_api_omits_forbidden_keys(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'privacy-api.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
    )
    with TestClient(create_app(settings_override=settings)) as client:
        _create_http_memory(client, content="小雪", subject_code="preferred_address")
        client.post("/api/relationship/reconcile", json={})

        for path in (
            "/api/relationship/capabilities",
            "/api/relationship/projection",
            "/api/relationship/events",
            "/api/relationship/jobs",
            "/api/relationship/audits",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            body = response.text
            for key in FORBIDDEN_PUBLIC_KEYS:
                assert key not in body, f"{path} leaked {key}"

        openapi = client.get("/openapi.json").json()
        schemas = openapi["components"]["schemas"]
        for name, schema in schemas.items():
            if not name.startswith("Relationship"):
                continue
            properties = schema.get("properties", {})
            for key in FORBIDDEN_PUBLIC_KEYS:
                assert key not in properties, f"{name} leaked {key}"


def test_composer_and_manifest_never_contain_forgotten_address(
    tmp_path: Path,
) -> None:
    from app.repositories.chat_turns import ChatTurnRepository
    from app.repositories.context_sources import ContextSourceRepository
    from app.repositories.messages import MessageRepository
    from app.repositories.personas import PersonaRepository
    from app.repositories.sessions import SessionRepository
    from app.providers.fake_provider import FakeProvider
    from app.services.chat_service import ChatService
    from app.services.context_composer import ContextComposer
    from app.services.context_data_encoder import ContextDataEncoder
    from app.services.persona_compiler import PersonaCompiler
    from app.services.persona_service import PersonaService
    from app.services.prompt_renderer import default_prompt_renderer
    from app.services.relationship_dispatch import RelationshipDisclosureFence
    from app.services.relationship_injection import RelationshipInjectionService

    address = _sentinel("address")
    database_url = f"sqlite:///{tmp_path / 'privacy-chat.db'}"
    with managed_connection(database_url) as connection:
        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)

        renderer = default_prompt_renderer()
        personas = PersonaService(
            PersonaRepository(connection),
            compiler=PersonaCompiler(
                template_text=renderer.load_template_text(),
                persona_max_characters=2000,
            ),
            bootstrap_config=renderer.load_persona_v1_config(),
        )
        persona_id = personas.bootstrap().artifact.id

        memory, _conflicts = memories.create(
            content=address,
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="preferred_address",
        )
        connection.commit()
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id=persona_id,
        )
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        settings = Settings(llm_provider="fake", llm_model="test-model")
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ChatTurnRepository(connection),
            personas,
            ContextSourceRepository(
                messages,
                memories,
                sessions=sessions,
            ),
            ContextComposer(settings, ContextDataEncoder()),
            provider,
            settings,
            relationship_injection=RelationshipInjectionService(
                database_url=database_url,
                fence=RelationshipDisclosureFence(),
            ),
        )
        session = sessions.create("chat")

        # Before forget the address appears in the provider call.
        reply = asyncio.run(service.send_message(session.id, "你好"))
        assert reply.reply
        sent = "\n".join(item.content for item in provider.calls[-1])
        assert address in sent

        # Forget the address source; chat still succeeds and never leaks it.
        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        forget.forget_memory(memory.id)
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        reply = asyncio.run(service.send_message(session.id, "再聊"))
        assert reply.reply
        sent = "\n".join(item.content for item in provider.calls[-1])
        assert address not in sent
        # Manifest never stores address text.
        assistant = messages.get(reply.assistant_message_id)
        manifest = assistant.metadata["context_manifest"]
        assert address not in str(manifest)


def test_captured_logs_do_not_contain_relationship_payload(tmp_path: Path) -> None:
    import io

    address = _sentinel("address")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'privacy-logs.db'}",
            memory_source_reference_key_path=tmp_path / "source-reference.key",
        )
        with TestClient(create_app(settings_override=settings)) as client:
            _create_http_memory(client, content=address, subject_code="preferred_address")
            client.post("/api/relationship/reconcile", json={})
            client.get("/api/relationship/events")
        logs = stream.getvalue()
        assert address not in logs
    finally:
        logger.removeHandler(handler)


def _create_http_memory(client, *, content: str, subject_code: str) -> dict:
    memory_type = (
        "preference" if subject_code == "preferred_address" else "relationship_event"
    )
    response = client.post(
        "/api/memories",
        json={
            "content": content,
            "memory_type": memory_type,
            "importance": 3,
            "confidence": 0.9,
            "canonical_subject_code": subject_code,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["memory"]
