from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
import sqlite3
from collections.abc import Callable

from app.domain.models import ChatRole
from app.domain.session_summary import (
    SummaryInjectionAuthoritySnapshot,
    SummarySourceFragment,
    SummarySuppressionState,
)
from app.repositories.summary_automation import DEFAULT_SUMMARY_INJECTION_SCOPE_ID
from app.services.credential_sanitizer import sanitize_credentials
from app.services.session_summary_contract import (
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    canonical_summary_source_set_hash,
)


_LOW_SIGNAL_TOKENS = {
    "我",
    "你",
    "他",
    "她",
    "它",
    "的",
    "了",
    "吗",
    "呢",
    "啊",
    "呀",
    "什么",
    "一下",
    "请",
    "帮我",
    "用户",
    "the",
    "a",
    "an",
    "is",
    "are",
}


@dataclass(frozen=True)
class SummarySelectionSnapshot:
    fragments: tuple[SummarySourceFragment, ...]
    authority: SummaryInjectionAuthoritySnapshot | None


@dataclass(frozen=True)
class _EligibleSummary:
    fragment: SummarySourceFragment
    updated_at: datetime
    lexical_score: float
    current_session: bool


class SummarySelectionRepository:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        min_lexical_relevance: float,
        session_deletion_generation: Callable[[str], int] | None = None,
    ) -> None:
        if not 0.0 <= min_lexical_relevance <= 1.0:
            raise ValueError("min_lexical_relevance must be between zero and one")
        self._connection = connection
        self._min_lexical_relevance = min_lexical_relevance
        self._session_deletion_generation = session_deletion_generation or (
            lambda _session_id: 0
        )

    def select(
        self,
        *,
        active_session_id: str,
        current_user_text: str,
        selected_recent_message_ids: tuple[str, ...],
        authority: SummaryInjectionAuthoritySnapshot | None,
    ) -> SummarySelectionSnapshot:
        if authority is None or not self._authority_is_current(authority):
            return SummarySelectionSnapshot((), None)

        current_barrier = self._current_barrier()
        if current_barrier is None:
            return SummarySelectionSnapshot((), authority)
        recent_turn_ids = self._recent_turn_ids(selected_recent_message_ids)
        query_tokens = _tokens(current_user_text)
        rows = self._connection.execute(
            """
            SELECT summary.*
            FROM session_summaries AS summary
            JOIN sessions AS session ON session.id=summary.session_id
            ORDER BY summary.session_id, summary.updated_at DESC, summary.id ASC
            """
        ).fetchall()

        eligible_by_session: dict[str, _EligibleSummary] = {}
        for row in rows:
            session_id = str(row["session_id"])
            candidate = self._eligible_candidate(
                row,
                authority=authority,
                current_barrier=current_barrier,
                active_session_id=active_session_id,
                recent_turn_ids=recent_turn_ids,
                query_tokens=query_tokens,
            )
            if candidate is not None:
                previous = eligible_by_session.get(session_id)
                if previous is None or self._is_later_candidate(
                    candidate,
                    previous,
                ):
                    eligible_by_session[session_id] = candidate

        ranked = sorted(
            eligible_by_session.values(),
            key=lambda item: (
                0 if item.current_session else 1,
                -item.lexical_score,
                -item.updated_at.timestamp(),
                item.fragment.summary_id,
            ),
        )
        fragments = tuple(
            item.fragment for item in ranked[: authority.max_fragment_count]
        )
        return SummarySelectionSnapshot(fragments, authority)

    def _eligible_candidate(
        self,
        row: sqlite3.Row,
        *,
        authority: SummaryInjectionAuthoritySnapshot,
        current_barrier: int,
        active_session_id: str,
        recent_turn_ids: set[str],
        query_tokens: set[str],
    ) -> _EligibleSummary | None:
        text = row["summary_text"]
        if (
            str(row["source"]) != "generated"
            or str(row["payload_state"]) != "active"
            or str(row["provenance_state"]) != "exact"
            or str(row["summarizer_schema_version"]) != SUMMARY_SCHEMA_VERSION
            or str(row["injection_schema_version"])
            != SUMMARY_INJECTION_SCHEMA_VERSION
            or int(row["observed_memory_summary_barrier"]) != current_barrier
            or row["source_set_hash"] is None
            or not isinstance(text, str)
            or not text.strip()
            or text != text.strip()
            or len(text) > authority.max_fragment_characters
            or sanitize_credentials(text) != (text, 0)
            or not self._metadata_is_valid(row["metadata_json"])
        ):
            return None

        source_rows = self._source_rows(str(row["id"]))
        source_identity = self._validated_source_identity(
            row,
            source_rows,
        )
        if source_identity is None:
            return None
        turn_ids, message_ids, expected_hash = source_identity
        if expected_hash != str(row["source_set_hash"]):
            return None
        if turn_ids & recent_turn_ids:
            return None
        if self._has_excluded_source(message_ids):
            return None
        suppression = self._suppression_snapshot(
            str(row["session_id"]),
            str(row["source_set_hash"]),
        )
        if suppression[2]:
            return None

        current_session = str(row["session_id"]) == active_session_id
        lexical_score = _lexical_score(query_tokens, _tokens(text))
        if not current_session and (
            lexical_score <= 0.0
            or lexical_score < self._min_lexical_relevance
        ):
            return None
        try:
            created_at = datetime.fromisoformat(str(row["created_at"]))
            updated_at = datetime.fromisoformat(str(row["updated_at"]))
        except ValueError:
            return None
        return _EligibleSummary(
            fragment=SummarySourceFragment(
                summary_id=str(row["id"]),
                source_session_id=str(row["session_id"]),
                source_kind="generated",
                created_at=created_at,
                summary_text=text,
                observed_barrier_generation=current_barrier,
                source_set_hash=str(row["source_set_hash"]),
                suppression_generation=suppression[0],
                suppression_state=suppression[1],
                summarizer_schema_version=str(
                    row["summarizer_schema_version"]
                ),
                injection_schema_version=str(row["injection_schema_version"]),
                source_turn_ids=tuple(
                    sorted(
                        turn_ids,
                        key=lambda turn_id: next(
                            index
                            for index, source_row in enumerate(source_rows)
                            if str(source_row["chat_turn_id"]) == turn_id
                        ),
                    )
                ),
                source_message_ids=message_ids,
                source_session_deletion_generation=(
                    self._session_deletion_generation(str(row["session_id"]))
                ),
            ),
            updated_at=updated_at,
            lexical_score=lexical_score,
            current_session=current_session,
        )

    @staticmethod
    def _is_later_candidate(
        candidate: _EligibleSummary,
        previous: _EligibleSummary,
    ) -> bool:
        if candidate.updated_at != previous.updated_at:
            return candidate.updated_at > previous.updated_at
        return candidate.fragment.summary_id < previous.fragment.summary_id

    def _authority_is_current(
        self,
        authority: SummaryInjectionAuthoritySnapshot,
    ) -> bool:
        row = self._connection.execute(
            "SELECT * FROM summary_injection_consents WHERE scope_id=?",
            (DEFAULT_SUMMARY_INJECTION_SCOPE_ID,),
        ).fetchone()
        if row is None:
            return False
        try:
            fields = json.loads(str(row["disclosed_fields_json"]))
        except (TypeError, ValueError):
            return False
        return (
            str(row["status"]) == "granted"
            and int(row["generation"]) == authority.generation
            and row["chat_provider_fingerprint"] == authority.policy_fingerprint
            and row["disclosure_version"] == authority.disclosure_version
            and isinstance(fields, list)
            and tuple(fields) == authority.disclosed_fields
            and int(row["max_fragment_count"])
            == authority.max_fragment_count
            and int(row["max_fragment_characters"])
            == authority.max_fragment_characters
            and int(row["max_total_characters"])
            == authority.max_total_characters
        )

    def _current_barrier(self) -> int | None:
        row = self._connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
        ).fetchone()
        return int(row["generation"]) if row is not None else None

    def _recent_turn_ids(self, message_ids: tuple[str, ...]) -> set[str]:
        if not message_ids:
            return set()
        placeholders = ", ".join("?" for _ in message_ids)
        rows = self._connection.execute(
            f"""
            SELECT id FROM chat_turns
            WHERE user_message_id IN ({placeholders})
               OR assistant_message_id IN ({placeholders})
            """,
            (*message_ids, *message_ids),
        ).fetchall()
        return {str(row["id"]) for row in rows}

    def _source_rows(self, summary_id: str) -> list[sqlite3.Row]:
        return self._connection.execute(
            """
            SELECT source.chat_turn_id, source.message_id, source.turn_order,
                   source.message_order_in_turn, source.source_order,
                   turn.session_id AS turn_session_id,
                   turn.user_message_id, turn.assistant_message_id,
                   turn.turn_order AS durable_turn_order,
                   message.session_id AS message_session_id,
                   message.role AS message_role
            FROM session_summary_sources AS source
            JOIN chat_turns AS turn ON turn.id=source.chat_turn_id
            JOIN messages AS message ON message.id=source.message_id
            WHERE source.summary_id=?
            ORDER BY source.source_order
            """,
            (summary_id,),
        ).fetchall()

    @staticmethod
    def _validated_source_identity(
        summary: sqlite3.Row,
        rows: list[sqlite3.Row],
    ) -> tuple[set[str], tuple[str, ...], str] | None:
        count = int(summary["message_count"])
        if count < 2 or count % 2 or len(rows) != count:
            return None
        if [int(row["source_order"]) for row in rows] != list(range(count)):
            return None

        session_id = str(summary["session_id"])
        turns: list[dict[str, object]] = []
        turn_ids: set[str] = set()
        message_ids: list[str] = []
        previous_turn_order = 0
        for index in range(0, count, 2):
            user, assistant = rows[index : index + 2]
            turn_id = str(user["chat_turn_id"])
            turn_order = int(user["turn_order"])
            if (
                str(assistant["chat_turn_id"]) != turn_id
                or int(assistant["turn_order"]) != turn_order
                or turn_order <= previous_turn_order
                or int(user["message_order_in_turn"]) != 0
                or int(assistant["message_order_in_turn"]) != 1
                or str(user["turn_session_id"]) != session_id
                or str(assistant["turn_session_id"]) != session_id
                or int(user["durable_turn_order"]) != turn_order
                or int(assistant["durable_turn_order"]) != turn_order
                or str(user["message_session_id"]) != session_id
                or str(assistant["message_session_id"]) != session_id
                or str(user["message_role"]) != ChatRole.USER.value
                or str(assistant["message_role"]) != ChatRole.ASSISTANT.value
                or str(user["message_id"]) != str(user["user_message_id"])
                or str(assistant["message_id"])
                != str(assistant["assistant_message_id"])
            ):
                return None
            user_id = str(user["message_id"])
            assistant_id = str(assistant["message_id"])
            turn_ids.add(turn_id)
            message_ids.extend((user_id, assistant_id))
            turns.append(
                {
                    "turn_id": turn_id,
                    "turn_order": turn_order,
                    "messages": (
                        {
                            "message_id": user_id,
                            "message_order_in_turn": 0,
                        },
                        {
                            "message_id": assistant_id,
                            "message_order_in_turn": 1,
                        },
                    ),
                }
            )
            previous_turn_order = turn_order
        expected_hash = canonical_summary_source_set_hash(
            session_id=session_id,
            turns=turns,
        )
        return turn_ids, tuple(message_ids), expected_hash

    def _has_excluded_source(self, message_ids: tuple[str, ...]) -> bool:
        placeholders = ", ".join("?" for _ in message_ids)
        return self._connection.execute(
            f"SELECT 1 FROM memory_summary_source_exclusions "
            f"WHERE source_message_id IN ({placeholders}) LIMIT 1",
            message_ids,
        ).fetchone() is not None

    def _suppression_snapshot(
        self,
        session_id: str,
        source_set_hash: str,
    ) -> tuple[int, SummarySuppressionState | None, bool]:
        row = self._connection.execute(
            """
            SELECT generation, state FROM summary_source_suppressions
            WHERE session_id=? AND source_set_hash=?
            """,
            (session_id, source_set_hash),
        ).fetchone()
        if row is None:
            return 0, None, False
        try:
            state = SummarySuppressionState(str(row["state"]))
        except ValueError:
            return int(row["generation"]), None, True
        return int(row["generation"]), state, state in {
            SummarySuppressionState.SUPPRESSED,
            SummarySuppressionState.REBUILD_AUTHORIZED,
            SummarySuppressionState.REBUILD_IN_PROGRESS,
        }

    @staticmethod
    def _metadata_is_valid(raw: object) -> bool:
        try:
            metadata = json.loads(str(raw))
        except (TypeError, ValueError):
            return False
        if not isinstance(metadata, dict):
            return False
        if metadata.get("corrupt") is True:
            return False
        if metadata.get("integrity_state") not in {None, "valid"}:
            return False
        if metadata.get("integrity_flag") not in {None, False, "valid"}:
            return False
        return True


def _ascii_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _LOW_SIGNAL_TOKENS
    }


def _cjk_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for run in re.findall(r"[一-鿿]+", text):
        if run not in _LOW_SIGNAL_TOKENS and len(run) >= 2:
            tokens.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                token = run[index : index + size]
                if token not in _LOW_SIGNAL_TOKENS:
                    tokens.add(token)
    return tokens


def _tokens(text: str) -> set[str]:
    return _ascii_tokens(text) | _cjk_tokens(text)


def _lexical_score(query_tokens: set[str], summary_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & summary_tokens) / len(query_tokens)
