from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole, MemoryType, MemoryVersionSourceKind, Message
from app.domain.persona import PersonaArtifact, PersonaPayloadState
from app.repositories.memories import StructuredMemoryContextSource
from app.repositories.sqlite import managed_connection
from app.services.context_composer import ContextComposer, ContextCompositionRequest
from app.services.context_data_encoder import ContextDataEncoder, EmotionExpressionView
import asyncio

from app.services.relationship_dispatch import RelationshipDisclosureFence
from app.services.relationship_injection import RelationshipInjectionService

from tests.test_relationship_projector import _BASE_TIME


def _run(coro):
    return asyncio.run(coro)


def _persona(prompt: str = "persona rules") -> PersonaArtifact:
    return PersonaArtifact(
        id="persona-1",
        version=1,
        payload_state=PersonaPayloadState.ACTIVE,
        schema_version="persona-schema-v1",
        ruleset_version="persona-ruleset-v1",
        template_version="persona-template-v1",
        compiler_version="persona-compiler-v1",
        source_content={"identity": {"name": "test"}},
        rendered_system_prompt=prompt,
        content_identity_hash="a" * 64,
        behavior_fingerprint="b" * 64,
        created_at=datetime(2026, 7, 21, tzinfo=UTC),
        redacted_at=None,
        redaction_reason_code=None,
    )


def _relationship() -> dict[str, object]:
    return {
        "authority": "derived_relationship_projection_not_fact",
        "projection_id": "projection-abc",
        "projection_version": 1,
        "familiarity_bucket": "steady",
        "preferred_address": "小雪",
        "relationship_summary_code": "steady",
        "persona_artifact_id": "persona-1",
        "projection_rule_version": "relationship-projection-v1",
    }


def _request(relationship=None) -> ContextCompositionRequest:
    return ContextCompositionRequest(
        provider_name="fake",
        session_id="session-1",
        current_user_message_id="current-id",
        current_user_text="current user",
        persona=_persona(),
        recent_messages=(),
        memories=(),
        emotion=None,
        relationship=relationship,
        summaries=(),
    )


def test_injection_service_neutralizes_relationship_when_revalidation_fails(
    tmp_path: Path,
) -> None:
    """If the relationship projection is no longer valid at pre-dispatch time
    (suppressed/redacted/forgotten), the injection service must replace it with
    a neutral view while chat still succeeds."""
    with managed_connection(f"sqlite:///{tmp_path / 'inject.db'}") as connection:
        fence = RelationshipDisclosureFence()
        service = RelationshipInjectionService(
            database_url=f"sqlite:///{tmp_path / 'inject.db'}",
            fence=fence,
        )

        # No projection exists in the database -> neutral view with no address.
        result = _run(
            service.revalidate_or_neutral(
                relationship=_relationship(),
                now=_BASE_TIME,
            )
        )

        assert result is not None
        assert result.get("preferred_address") is None
        assert result.get("familiarity_bucket") == "steady"
        assert result.get("projection_id") == "neutral"


def test_injection_service_keeps_valid_relationship(tmp_path: Path) -> None:
    """A still-valid projection survives pre-dispatch revalidation."""
    with managed_connection(f"sqlite:///{tmp_path / 'inject-ok.db'}") as connection:
        # Seed persona + source and reconcile so a real projection exists.
        from app.domain.models import MemorySource
        from app.repositories.memories import MemoryRepository
        from app.services.memory_source_reference import MemorySourceReferenceService
        from app.services.relationship_reconciler import RelationshipReconciler
        from app.services.relationship_scheduler import RelationshipScheduler
        from app.services.persona_compiler import PersonaCompiler
        from app.services.persona_service import PersonaService
        from app.services.prompt_renderer import default_prompt_renderer

        compiler = PersonaCompiler(
            template_text=default_prompt_renderer().load_template_text(),
            persona_max_characters=2000,
        )
        repo = __import__(
            "app.repositories.personas", fromlist=["PersonaRepository"]
        ).PersonaRepository(connection)
        service_p = PersonaService(
            repo,
            compiler=compiler,
            bootstrap_config=default_prompt_renderer().load_persona_v1_config,
        )
        first = service_p.bootstrap()
        persona_id = first.artifact.id

        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        memory, _conflicts = memories.create(
            content="一起赏雪",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )
        connection.commit()
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id=persona_id,
        )
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        fence = RelationshipDisclosureFence()
        service = RelationshipInjectionService(
            database_url=f"sqlite:///{tmp_path / 'inject-ok.db'}",
            fence=fence,
        )
        from app.repositories.relationship_projections import (
            RelationshipProjectionRepository,
        )

        projection = RelationshipProjectionRepository(connection).current()
        assert projection is not None
        relationship = {
            "authority": "derived_relationship_projection_not_fact",
            "projection_id": projection.projection_id,
            "projection_version": projection.version,
            "familiarity_bucket": "steady",
            "preferred_address": None,
            "relationship_summary_code": projection.relationship_summary_code.value,
            "persona_artifact_id": projection.persona_artifact_id,
            "projection_rule_version": projection.projection_rule_version,
        }

        result = _run(
            service.revalidate_or_neutral(
                relationship=relationship,
                now=_BASE_TIME + timedelta(days=1),
            )
        )
        assert result is not None
        assert result["projection_id"] == projection.projection_id


def _chat_service_with_relationship(
    connection,
    *,
    database_url: str,
    provider,
    fence: RelationshipDisclosureFence,
):
    """Build a real ChatService wired with relationship pre-dispatch injection."""
    from app.providers.fake_provider import FakeProvider
    from app.repositories.chat_turns import ChatTurnRepository
    from app.repositories.context_sources import ContextSourceRepository
    from app.repositories.memories import MemoryRepository
    from app.repositories.messages import MessageRepository
    from app.repositories.personas import PersonaRepository
    from app.repositories.sessions import SessionRepository
    from app.services.chat_service import ChatService
    from app.services.persona_compiler import PersonaCompiler
    from app.services.persona_service import PersonaService
    from app.services.prompt_renderer import default_prompt_renderer

    settings = Settings(llm_provider="fake", llm_model="test-model")
    sessions = SessionRepository(connection)
    messages = MessageRepository(connection)
    renderer = default_prompt_renderer()
    personas = PersonaService(
        PersonaRepository(connection),
        compiler=PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=settings.persona_max_characters,
        ),
        bootstrap_config=renderer.load_persona_v1_config(),
    )
    personas.bootstrap()
    memories = MemoryRepository(connection)
    sources = ContextSourceRepository(
        messages,
        memories,
        sessions=sessions,
    )
    injection = RelationshipInjectionService(
        database_url=database_url,
        fence=fence,
    )
    service = ChatService(
        sessions,
        messages,
        ChatTurnRepository(connection),
        personas,
        sources,
        ContextComposer(settings, ContextDataEncoder()),
        provider,
        settings,
        relationship_injection=injection,
    )
    return service, sessions


def test_chat_sends_verified_relationship_and_neutral_after_forget(
    tmp_path: Path,
) -> None:
    """The real chat flow injects the verified projection pre-dispatch and, after
    a true forget, never leaks the forgotten address to the Provider."""
    import secrets

    from app.domain.models import MemorySource
    from app.providers.fake_provider import FakeProvider
    from app.repositories.memories import MemoryRepository
    from app.repositories.versioned_memories import VersionedMemoryRepository
    from app.services.memory_forget_service import MemoryForgetService
    from app.services.memory_source_reference import MemorySourceReferenceService
    from app.services.relationship_reconciler import RelationshipReconciler
    from app.services.relationship_scheduler import RelationshipScheduler

    sentinel = f"address-{secrets.token_hex(6)}"
    database_url = f"sqlite:///{tmp_path / 'chat-relationship.db'}"
    provider = FakeProvider()
    fence = RelationshipDisclosureFence()
    with managed_connection(database_url) as connection:
        from app.repositories.personas import PersonaRepository
        from app.services.persona_compiler import PersonaCompiler
        from app.services.persona_service import PersonaService
        from app.services.prompt_renderer import default_prompt_renderer

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

        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        memory, _conflicts = memories.create(
            content=sentinel,
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

        service, sessions = _chat_service_with_relationship(
            connection,
            database_url=database_url,
            provider=provider,
            fence=fence,
        )
        session = sessions.create("active")

        first = _run(service.send_message(session.id, "你好"))
        assert first.reply
        first_payload = "\n".join(
            item.content for item in provider.calls[0]
        )
        assert sentinel in first_payload
        assert '"authority":"derived_relationship_projection_not_fact"' in (
            first_payload
        )
        assistant = first.assistant_message_id

        # True forget of the address source: relationship layer must neutralize.
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        forget.forget_memory(memory.id)
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        second = _run(service.send_message(session.id, "再聊"))
        assert second.reply
        second_payload = "\n".join(
            item.content for item in provider.calls[1]
        )
        # Provider never sees the forgotten address after forget.
        assert sentinel not in second_payload
        assert second.assistant_message_id != assistant
