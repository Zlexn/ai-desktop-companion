from dataclasses import dataclass
from typing import Protocol

from app.domain.models import Memory, Message
from app.domain.session_summary import (
    SummaryInjectionAuthoritySnapshot,
    SummarySourceFragment,
)
from app.repositories.memories import (
    MemoryRepository,
    StructuredMemoryContextSource,
)
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository


class SummarySourceSelection(Protocol):
    def select(
        self,
        *,
        active_session_id: str,
        current_user_text: str,
        selected_recent_message_ids: tuple[str, ...],
        authority: SummaryInjectionAuthoritySnapshot | None,
    ): ...


@dataclass(frozen=True)
class ContextSourceSnapshot:
    recent_messages: tuple[Message, ...]
    memories: tuple[StructuredMemoryContextSource, ...]
    summaries: tuple[SummarySourceFragment, ...] = ()
    summary_authority: SummaryInjectionAuthoritySnapshot | None = None


class MemoryEmbeddingSearch(Protocol):
    def search_relevant(
        self,
        query: str,
        limit: int,
        min_score: float,
    ) -> list[Memory]: ...


class ContextSourceRepository:
    def __init__(
        self,
        messages: MessageRepository,
        memories: MemoryRepository | None,
        *,
        memory_retrieval_mode: str = "relevance",
        memory_embedding_service: MemoryEmbeddingSearch | None = None,
        memory_embedding_min_score: float = 0.35,
        sessions: SessionRepository | None = None,
        summary_selection: SummarySourceSelection | None = None,
        summary_authority: SummaryInjectionAuthoritySnapshot | None = None,
    ) -> None:
        self._messages = messages
        self._memories = memories
        self._memory_retrieval_mode = memory_retrieval_mode
        self._memory_embedding_service = memory_embedding_service
        self._memory_embedding_min_score = memory_embedding_min_score
        self._sessions = sessions
        self._summary_selection = summary_selection
        self._summary_authority = summary_authority

    def snapshot(
        self,
        *,
        session_id: str,
        current_user_message_id: str,
        query: str | None,
        recent_limit: int,
        memory_limit: int,
        memory_fallback_limit: int = 3,
    ) -> ContextSourceSnapshot:
        recent = self._messages.list_recent_excluding(
            session_id,
            current_user_message_id,
            recent_limit,
        )
        memories: list[StructuredMemoryContextSource] = []
        if self._memories is not None and memory_limit > 0:
            try:
                memories = self._memory_sources(
                    query=query,
                    memory_limit=memory_limit,
                    memory_fallback_limit=memory_fallback_limit,
                )
            except Exception:
                memories = []
        summaries: tuple[SummarySourceFragment, ...] = ()
        summary_authority: SummaryInjectionAuthoritySnapshot | None = None
        if self._summary_selection is not None:
            try:
                selection = self._summary_selection.select(
                    active_session_id=session_id,
                    current_user_text=query or "",
                    selected_recent_message_ids=tuple(
                        message.id for message in recent
                    ),
                    authority=self._summary_authority,
                )
                summaries = selection.fragments
                summary_authority = selection.authority
            except Exception:
                summaries = ()
                summary_authority = None
        return ContextSourceSnapshot(
            tuple(recent),
            tuple(memories),
            summaries,
            summary_authority,
        )

    def revalidate(
        self,
        *,
        session_id: str,
        current_user_message_id: str,
        query: str,
        snapshot: ContextSourceSnapshot,
    ) -> ContextSourceSnapshot | None:
        current_message = self._messages.get(current_user_message_id)
        if (
            (self._sessions is not None and self._sessions.get(session_id) is None)
            or current_message is None
            or current_message.session_id != session_id
        ):
            return None

        recent_by_id = {
            message.id: message
            for message in self._messages.list(session_id)
            if message.id != current_user_message_id
        }
        recent = tuple(
            recent_by_id[message.id]
            for message in snapshot.recent_messages
            if message.id in recent_by_id
        )

        memories: tuple[StructuredMemoryContextSource, ...] = ()
        if self._memories is not None:
            eligible_identities = {
                (memory.memory_id, memory.current_version_id)
                for memory in self._memories.list_context_sources(
                    None,
                    1_000_000,
                )
            }
            memories = tuple(
                source
                for source in snapshot.memories
                if (source.memory_id, source.current_version_id)
                in eligible_identities
            )

        summaries: tuple[SummarySourceFragment, ...] = ()
        authority: SummaryInjectionAuthoritySnapshot | None = None
        if self._summary_selection is not None and snapshot.summaries:
            try:
                selection = self._summary_selection.select(
                    active_session_id=session_id,
                    current_user_text=query,
                    selected_recent_message_ids=tuple(
                        message.id for message in recent
                    ),
                    authority=snapshot.summary_authority,
                )
                captured_by_id = {
                    fragment.summary_id: fragment
                    for fragment in snapshot.summaries
                }
                selected = {
                    fragment.summary_id: fragment
                    for fragment in selection.fragments
                    if (
                        captured := captured_by_id.get(fragment.summary_id)
                    ) is not None
                    and self._same_summary_snapshot(captured, fragment)
                }
                current_fragments = tuple(
                    selected[fragment.summary_id]
                    for fragment in snapshot.summaries
                    if fragment.summary_id in selected
                )
                if (
                    selection.authority == snapshot.summary_authority
                    and len(current_fragments) == len(snapshot.summaries)
                ):
                    summaries = current_fragments
                    authority = selection.authority
                else:
                    summaries = ()
                    authority = None
            except Exception:
                summaries = ()
                authority = None
        return ContextSourceSnapshot(recent, memories, summaries, authority)

    @staticmethod
    def _same_summary_snapshot(
        captured: SummarySourceFragment,
        current: SummarySourceFragment,
    ) -> bool:
        return (
            captured.summary_id == current.summary_id
            and captured.source_session_id == current.source_session_id
            and captured.source_kind == current.source_kind
            and captured.created_at == current.created_at
            and captured.summary_text == current.summary_text
            and captured.observed_barrier_generation
            == current.observed_barrier_generation
            and captured.source_set_hash == current.source_set_hash
            and captured.suppression_generation == current.suppression_generation
            and captured.suppression_state == current.suppression_state
            and captured.summarizer_schema_version
            == current.summarizer_schema_version
            and captured.injection_schema_version
            == current.injection_schema_version
            and captured.source_turn_ids == current.source_turn_ids
            and captured.source_message_ids == current.source_message_ids
            and captured.source_session_deletion_generation
            == current.source_session_deletion_generation
        )

    def _memory_sources(
        self,
        *,
        query: str | None,
        memory_limit: int,
        memory_fallback_limit: int,
    ) -> list[StructuredMemoryContextSource]:
        if self._memories is None:
            return []
        memories: list[StructuredMemoryContextSource] = []
        if (
            self._memory_retrieval_mode == "embedding"
            and query is not None
            and query.strip()
            and self._memory_embedding_service is not None
        ):
            try:
                selected = self._memory_embedding_service.search_relevant(
                    query,
                    memory_limit,
                    self._memory_embedding_min_score,
                )
            except Exception:
                selected = []
            memories = self._memories.context_sources_for_memories(selected)
        if not memories:
            memories = self._memories.list_context_sources(
                query,
                memory_limit,
                memory_fallback_limit,
            )
        return memories
