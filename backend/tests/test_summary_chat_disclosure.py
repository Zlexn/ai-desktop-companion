from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.domain.models import ChatRole, MemorySource, MemoryType
from app.domain.session_summary import (
    SummaryInjectionAuthoritySnapshot,
    SummarySourceFragment,
)
from app.providers.fake_provider import FakeProvider
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.context_sources import ContextSourceRepository
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.personas import PersonaRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_selection import SummarySelectionSnapshot
from app.services.chat_service import ChatService
from app.services.context_composer import ContextComposer
from app.services.context_data_encoder import ContextDataEncoder
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
from app.services.prompt_renderer import default_prompt_renderer
from app.services.summary_dispatch import SummaryDisclosureFence


class TransactionCheckingProvider(FakeProvider):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self._connection = connection

    async def generate(self, messages, options):
        assert self._connection.in_transaction is False
        return await super().generate(messages, options)


class MutableSummarySelection:
    def __init__(
        self,
        fragment: SummarySourceFragment
        | tuple[SummarySourceFragment, ...],
        authority: SummaryInjectionAuthoritySnapshot,
    ) -> None:
        self.fragments = (
            fragment if isinstance(fragment, tuple) else (fragment,)
        )
        self.authority = authority
        self.invalid_summary_ids: set[str] = set()
        self.calls = 0

    def select(self, **_kwargs) -> SummarySelectionSnapshot:
        self.calls += 1
        return SummarySelectionSnapshot(
            tuple(
                fragment
                for fragment in self.fragments
                if fragment.summary_id not in self.invalid_summary_ids
            ),
            self.authority,
        )


def _authority() -> SummaryInjectionAuthoritySnapshot:
    return SummaryInjectionAuthoritySnapshot(
        generation=1,
        policy_fingerprint="policy",
        disclosure_version="summary-injection-disclosure-v1",
        disclosed_fields=(
            "summary_text",
            "low_trust_type_label",
            "source_session_id",
            "summary_id",
            "source_kind",
            "created_at",
        ),
        max_fragment_count=2,
        max_fragment_characters=1_000,
        max_total_characters=1_600,
    )


def _fragment(
    *,
    summary_id: str = "summary-selected",
    text: str = "SUMMARY_DISCLOSURE_SENTINEL",
) -> SummarySourceFragment:
    return SummarySourceFragment(
        summary_id=summary_id,
        source_session_id="summary-source-session",
        source_kind="generated",
        created_at=datetime(2026, 7, 24, tzinfo=UTC),
        summary_text=text,
        observed_barrier_generation=0,
        source_set_hash="private-source-set-hash",
        suppression_generation=0,
        suppression_state=None,
        summarizer_schema_version="session-summary-v2",
        injection_schema_version="summary-injection-v1",
        source_turn_ids=("source-turn",),
        source_message_ids=("source-user", "source-assistant"),
    )


def _service(
    connection: sqlite3.Connection,
    *,
    provider: FakeProvider,
    fence: SummaryDisclosureFence,
    selector: MutableSummarySelection,
) -> tuple[ChatService, SessionRepository, MessageRepository, MemoryRepository]:
    settings = Settings(llm_provider="fake", llm_model="test-model")
    sessions = SessionRepository(connection)
    messages = MessageRepository(connection)
    memories = MemoryRepository(connection)
    renderer = default_prompt_renderer()
    persona_repository = PersonaRepository(connection)
    personas = PersonaService(
        persona_repository,
        compiler=PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=settings.persona_max_characters,
        ),
        bootstrap_config=renderer.load_persona_v1_config(),
    )
    personas.bootstrap()
    sources = ContextSourceRepository(
        messages,
        memories,
        sessions=sessions,
        summary_selection=selector,
        summary_authority=selector.authority,
    )
    return (
        ChatService(
            sessions,
            messages,
            ChatTurnRepository(connection),
            personas,
            sources,
            ContextComposer(settings, ContextDataEncoder()),
            provider,
            settings,
            summary_disclosure_fence=fence,
        ),
        sessions,
        messages,
        memories,
    )


async def _release_mutation(mutation) -> None:
    await mutation.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_queued_summary_mutation_recomposes_zero_summary_before_send(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-disclosure.db'}"
    with managed_connection(database_url) as connection:
        provider = FakeProvider()
        fence = SummaryDisclosureFence()
        selector = MutableSummarySelection(_fragment(), _authority())
        service, sessions, messages, _memories = _service(
            connection,
            provider=provider,
            fence=fence,
            selector=selector,
        )
        session = sessions.create("active")
        mutation = fence.begin_mutation()
        await mutation.__aenter__()
        task = asyncio.create_task(service.send_message(session.id, "hello"))
        await asyncio.sleep(0)
        selector.invalid_summary_ids.add("summary-selected")
        await _release_mutation(mutation)

        reply = await task

        assert reply.reply
        assert selector.calls == 2
        assert len(provider.calls) == 1
        sent = "\n".join(item.content for item in provider.calls[0])
        assert "SUMMARY_DISCLOSURE_SENTINEL" not in sent
        assistant = messages.get(reply.assistant_message_id)
        assert assistant is not None
        assert assistant.metadata["context_manifest"]["selected_summary_ids"] == []


@pytest.mark.asyncio
async def test_zero_summary_fallback_drops_newly_ineligible_memory_and_recent_ids(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-fallback-context.db'}"
    with managed_connection(database_url) as connection:
        provider = FakeProvider()
        fence = SummaryDisclosureFence()
        selector = MutableSummarySelection(_fragment(), _authority())
        service, sessions, messages, memories = _service(
            connection,
            provider=provider,
            fence=fence,
            selector=selector,
        )
        session = sessions.create("active")
        old_message = messages.add(
            session.id,
            ChatRole.USER,
            "RECENT_CONTEXT_MUST_DROP",
        )
        memory, _conflicts = memories.create(
            content="MEMORY_CONTEXT_MUST_DROP",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        mutation = fence.begin_mutation()
        await mutation.__aenter__()
        task = asyncio.create_task(service.send_message(session.id, "hello"))
        await asyncio.sleep(0)
        selector.invalid_summary_ids.add("summary-selected")
        memories.archive(memory.id)
        connection.execute("DELETE FROM messages WHERE id=?", (old_message.id,))
        connection.commit()
        await _release_mutation(mutation)

        reply = await task

        sent = "\n".join(item.content for item in provider.calls[0])
        assert "SUMMARY_DISCLOSURE_SENTINEL" not in sent
        assert "RECENT_CONTEXT_MUST_DROP" not in sent
        assert "MEMORY_CONTEXT_MUST_DROP" not in sent
        assistant = messages.get(reply.assistant_message_id)
        assert assistant is not None
        manifest = assistant.metadata["context_manifest"]
        assert manifest["selected_summary_ids"] == []
        assert old_message.id not in manifest["selected_recent_message_ids"]


@pytest.mark.asyncio
async def test_partial_summary_invalidation_drops_all_summaries(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'partial-summary-invalidation.db'}"
    with managed_connection(database_url) as connection:
        provider = FakeProvider()
        fence = SummaryDisclosureFence()
        first = _fragment()
        second = _fragment(
            summary_id="summary-second",
            text="SECOND_SUMMARY_SENTINEL",
        )
        selector = MutableSummarySelection((first, second), _authority())
        service, sessions, messages, _memories = _service(
            connection,
            provider=provider,
            fence=fence,
            selector=selector,
        )
        session = sessions.create("active")
        mutation = fence.begin_mutation()
        await mutation.__aenter__()
        task = asyncio.create_task(service.send_message(session.id, "hello"))
        await asyncio.sleep(0)
        selector.invalid_summary_ids.add(first.summary_id)
        await _release_mutation(mutation)

        reply = await task

        sent = "\n".join(item.content for item in provider.calls[0])
        assert "SUMMARY_DISCLOSURE_SENTINEL" not in sent
        assert "SECOND_SUMMARY_SENTINEL" not in sent
        assistant = messages.get(reply.assistant_message_id)
        assert assistant is not None
        assert assistant.metadata["context_manifest"]["selected_summary_ids"] == []


@pytest.mark.asyncio
async def test_provider_identity_mismatch_fails_closed_to_zero_summaries(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'provider-mismatch.db'}"
    with managed_connection(database_url) as connection:
        provider = FakeProvider()
        provider.provider_name = "other-provider"
        fence = SummaryDisclosureFence()
        selector = MutableSummarySelection(_fragment(), _authority())
        service, sessions, messages, _memories = _service(
            connection,
            provider=provider,
            fence=fence,
            selector=selector,
        )
        session = sessions.create("active")

        reply = await service.send_message(session.id, "hello")

        sent = "\n".join(item.content for item in provider.calls[0])
        assert "SUMMARY_DISCLOSURE_SENTINEL" not in sent
        assistant = messages.get(reply.assistant_message_id)
        assert assistant is not None
        assert assistant.metadata["context_manifest"]["selected_summary_ids"] == []


@pytest.mark.asyncio
async def test_active_session_deletion_before_summary_dispatch_aborts_provider(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'active-session-delete.db'}"
    with managed_connection(database_url) as connection:
        provider = FakeProvider()
        fence = SummaryDisclosureFence()
        selector = MutableSummarySelection(_fragment(), _authority())
        service, sessions, _messages, _memories = _service(
            connection,
            provider=provider,
            fence=fence,
            selector=selector,
        )
        session = sessions.create("active")
        mutation = fence.begin_mutation()
        await mutation.__aenter__()
        task = asyncio.create_task(service.send_message(session.id, "hello"))
        await asyncio.sleep(0)
        selector.invalid_summary_ids.add("summary-selected")
        sessions.delete(session.id)
        await _release_mutation(mutation)

        with pytest.raises(NotFoundError):
            await task
        assert provider.calls == []


@pytest.mark.asyncio
async def test_current_summary_snapshot_is_sent_under_fence_without_sqlite_transaction(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'current-summary.db'}"
    with managed_connection(database_url) as connection:
        provider = TransactionCheckingProvider(connection)
        fence = SummaryDisclosureFence()
        selector = MutableSummarySelection(_fragment(), _authority())
        service, sessions, messages, _memories = _service(
            connection,
            provider=provider,
            fence=fence,
            selector=selector,
        )
        session = sessions.create("active")

        reply = await service.send_message(session.id, "hello")

        assert selector.calls == 2
        assert connection.in_transaction is False
        sent = "\n".join(item.content for item in provider.calls[0])
        assert "SUMMARY_DISCLOSURE_SENTINEL" in sent
        assistant = messages.get(reply.assistant_message_id)
        assert assistant is not None
        assert assistant.metadata["context_manifest"]["selected_summary_ids"] == [
            "summary-selected"
        ]
