from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from app.domain.models import ChatRole
from app.domain.session_summary import SummaryJobKind
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import connect, init_db
from app.repositories.summary_automation import (
    SummaryAutomationRepository,
    SummaryInjectionPolicy,
)
from app.repositories.summary_selection import SummarySelectionRepository
from app.services.session_summary_contract import (
    SUMMARY_INJECTION_DISCLOSED_FIELDS,
    SUMMARY_INJECTION_DISCLOSURE_VERSION,
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)


@pytest.fixture
def connection(tmp_path) -> sqlite3.Connection:
    connection = connect(f"sqlite:///{tmp_path / 'summary-selection.db'}")
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def _policy(
    *,
    max_fragments: int = 8,
    max_fragment_characters: int = 1_000,
    max_total_characters: int = 4_000,
) -> SummaryInjectionPolicy:
    return SummaryInjectionPolicy(
        route="remote",
        disclosure_version=SUMMARY_INJECTION_DISCLOSURE_VERSION,
        purpose="inject bounded low-trust session continuity summaries into chat context",
        chat_provider="deepseek",
        chat_model="deepseek-chat",
        endpoint_policy="openai-compatible-v1",
        injection_schema_version=SUMMARY_INJECTION_SCHEMA_VERSION,
        disclosed_fields=SUMMARY_INJECTION_DISCLOSED_FIELDS,
        max_fragment_count=max_fragments,
        max_fragment_characters=max_fragment_characters,
        max_total_characters=max_total_characters,
    )


def _grant(connection: sqlite3.Connection, policy: SummaryInjectionPolicy):
    automation = SummaryAutomationRepository(connection)
    current = automation.get_injection_authority()
    automation.mutate_injection(
        action="grant",
        expected_generation=current.generation,
        policy=policy,
    )
    authority = automation.valid_injection_snapshot(policy)
    assert authority is not None
    return authority


def _add_turn(
    connection: sqlite3.Connection,
    session_id: str,
    *,
    user_text: str,
    assistant_text: str,
):
    user = MessageRepository(connection).add(
        session_id,
        ChatRole.USER,
        user_text,
    )
    assistant, turn = ChatTurnRepository(connection).append_assistant_turn(
        session_id=session_id,
        user_message_id=user.id,
        content=assistant_text,
        metadata={},
    )
    return user, assistant, turn


def _insert_summary(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn,
    summary_id: str,
    text: str | None,
    updated_at: datetime,
    source: str = "generated",
    payload_state: str = "active",
    provenance_state: str = "exact",
    summarizer_schema: str = SUMMARY_SCHEMA_VERSION,
    injection_schema: str = SUMMARY_INJECTION_SCHEMA_VERSION,
    observed_barrier: int = 0,
    metadata_json: str = "{}",
    retain_covered_message_ids: bool = True,
) -> tuple[str, str, str]:
    snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
        session_id=session_id,
        after_turn_order=turn.turn_order - 1,
        max_turns=1,
        max_messages=2,
        max_characters=10_000,
    )
    assert snapshot.source_set_hash is not None
    job, _ = SummaryAutomationRepository(connection).reserve_job(
        snapshot=snapshot,
        job_kind=SummaryJobKind.INCREMENTAL,
        route="fake",
        provider=None,
        model=None,
        summarizer_schema_version=summarizer_schema,
        processing_consent_generation=0,
        processing_policy_fingerprint=None,
        provider_policy_fingerprint=f"fixture-{summary_id}",
        session_deletion_generation=0,
        suppression_generation=0,
        rebuild_authorization_generation=0,
        rebuild_permit_id=None,
    )
    claimed = SummaryAutomationRepository(connection).claim_job(
        job.id,
        max_attempts=3,
        summarizer_schema_version=summarizer_schema,
    )
    assert claimed is not None
    if source == "generated" and provenance_state == "exact":
        connection.execute(
            "INSERT INTO summary_commit_guards (job_id, summary_id) VALUES (?, ?)",
            (job.id, summary_id),
        )
    redacted = payload_state in {"redacted", "quarantined"}
    timestamp = updated_at.isoformat()
    connection.execute(
        """
        INSERT INTO session_summaries (
            id, session_id, summary_text, source,
            covered_message_start_id, covered_message_end_id,
            message_count, metadata_json, created_at, updated_at,
            observed_memory_summary_barrier, payload_state,
            source_set_hash, summarizer_schema_version,
            injection_schema_version, replaces_summary_id,
            provenance_state, redacted_at, redaction_reason_code
        ) VALUES (?, ?, ?, ?, ?, ?, 2, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            summary_id,
            session_id,
            text,
            source,
            (
                snapshot.turns[0].messages[0].id
                if retain_covered_message_ids
                else None
            ),
            (
                snapshot.turns[0].messages[1].id
                if retain_covered_message_ids
                else None
            ),
            metadata_json,
            timestamp,
            timestamp,
            observed_barrier,
            payload_state,
            snapshot.source_set_hash,
            summarizer_schema,
            injection_schema,
            provenance_state,
            timestamp if redacted else None,
            "fixture_unavailable" if redacted else None,
        ),
    )
    for source_row in connection.execute(
        "SELECT * FROM summary_job_sources WHERE job_id=? ORDER BY source_order",
        (job.id,),
    ).fetchall():
        connection.execute(
            """
            INSERT INTO session_summary_sources (
                summary_id, chat_turn_id, message_id, turn_order,
                message_order_in_turn, source_order
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                summary_id,
                source_row["chat_turn_id"],
                source_row["message_id"],
                source_row["turn_order"],
                source_row["message_order_in_turn"],
                source_row["source_order"],
            ),
        )
    connection.execute(
        "DELETE FROM summary_commit_guards WHERE job_id=?",
        (job.id,),
    )
    connection.execute("DELETE FROM summary_jobs WHERE id=?", (job.id,))
    connection.commit()
    return (
        snapshot.source_set_hash,
        snapshot.turns[0].messages[0].id,
        snapshot.turns[0].messages[1].id,
    )


def _selector(connection: sqlite3.Connection) -> SummarySelectionRepository:
    return SummarySelectionRepository(
        connection,
        min_lexical_relevance=0.15,
    )


def test_selects_latest_eligible_per_session_and_older_current_nonoverlap(
    connection: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC)
    sessions = SessionRepository(connection)
    active = sessions.create("active")
    other = sessions.create("other")
    irrelevant = sessions.create("irrelevant")

    _, _, active_old_turn = _add_turn(
        connection,
        active.id,
        user_text="以前讨论红茶计划",
        assistant_text="记录旧计划",
    )
    _insert_summary(
        connection,
        session_id=active.id,
        turn=active_old_turn,
        summary_id="active-old",
        text="较早的当前会话连续性",
        updated_at=now,
    )
    active_recent_user, active_recent_assistant, active_recent_turn = _add_turn(
        connection,
        active.id,
        user_text="最近一轮",
        assistant_text="最近回复",
    )
    _insert_summary(
        connection,
        session_id=active.id,
        turn=active_recent_turn,
        summary_id="active-overlap",
        text="不得与最近消息重叠",
        updated_at=now + timedelta(seconds=1),
    )

    _, _, other_old_turn = _add_turn(
        connection,
        other.id,
        user_text="旧红茶",
        assistant_text="旧回复",
    )
    _insert_summary(
        connection,
        session_id=other.id,
        turn=other_old_turn,
        summary_id="other-old",
        text="红茶旧安排",
        updated_at=now,
    )
    _, _, other_latest_turn = _add_turn(
        connection,
        other.id,
        user_text="新红茶",
        assistant_text="新回复",
    )
    _insert_summary(
        connection,
        session_id=other.id,
        turn=other_latest_turn,
        summary_id="other-latest",
        text="红茶计划已经更新",
        updated_at=now + timedelta(seconds=2),
    )
    _, _, irrelevant_turn = _add_turn(
        connection,
        irrelevant.id,
        user_text="天气",
        assistant_text="晴朗",
    )
    _insert_summary(
        connection,
        session_id=irrelevant.id,
        turn=irrelevant_turn,
        summary_id="irrelevant",
        text="天气晴朗",
        updated_at=now + timedelta(seconds=3),
    )
    authority = _grant(connection, _policy())

    selected = _selector(connection).select(
        active_session_id=active.id,
        current_user_text="继续红茶计划",
        selected_recent_message_ids=(
            active_recent_user.id,
            active_recent_assistant.id,
        ),
        authority=authority,
    )

    assert [fragment.summary_id for fragment in selected.fragments] == [
        "active-old",
        "other-latest",
    ]
    assert selected.authority == authority
    assert selected.fragments[0].observed_barrier_generation == 0
    assert selected.fragments[0].suppression_generation == 0
    assert selected.fragments[0].source_turn_ids == (active_old_turn.id,)
    assert len(selected.fragments[0].source_message_ids) == 2


def test_only_current_session_summary_overlapping_recent_turn_is_excluded(
    connection: sqlite3.Connection,
) -> None:
    session = SessionRepository(connection).create("active-overlap-only")
    user, assistant, turn = _add_turn(
        connection,
        session.id,
        user_text="红茶计划",
        assistant_text="继续讨论",
    )
    _insert_summary(
        connection,
        session_id=session.id,
        turn=turn,
        summary_id="only-overlap",
        text="红茶计划",
        updated_at=datetime.now(UTC),
    )
    authority = _grant(connection, _policy())

    selected = _selector(connection).select(
        active_session_id=session.id,
        current_user_text="红茶计划",
        selected_recent_message_ids=(user.id, assistant.id),
        authority=authority,
    )

    assert selected.fragments == ()


def test_latest_ineligible_cross_session_row_does_not_hide_older_eligible_row(
    connection: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC)
    sessions = SessionRepository(connection)
    active = sessions.create("active")
    other = sessions.create("other")
    _, _, older_turn = _add_turn(
        connection,
        other.id,
        user_text="红茶计划",
        assistant_text="继续",
    )
    _insert_summary(
        connection,
        session_id=other.id,
        turn=older_turn,
        summary_id="older-eligible",
        text="红茶计划",
        updated_at=now,
    )
    _, _, latest_turn = _add_turn(
        connection,
        other.id,
        user_text="天气",
        assistant_text="晴朗",
    )
    _insert_summary(
        connection,
        session_id=other.id,
        turn=latest_turn,
        summary_id="latest-zero-relevance",
        text="天气晴朗",
        updated_at=now + timedelta(seconds=1),
    )
    authority = _grant(connection, _policy())

    selected = _selector(connection).select(
        active_session_id=active.id,
        current_user_text="红茶计划",
        selected_recent_message_ids=(),
        authority=authority,
    )

    assert [item.summary_id for item in selected.fragments] == [
        "older-eligible"
    ]


def test_stable_ranking_uses_score_then_time_then_id(
    connection: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC)
    sessions = SessionRepository(connection)
    active = sessions.create("active")
    expected = []
    fixtures = (
        ("score-high", "红茶计划安排", now),
        ("later-b", "红茶", now + timedelta(seconds=1)),
        ("later-a", "红茶", now + timedelta(seconds=1)),
        ("older", "红茶", now),
    )
    for summary_id, text, updated_at in fixtures:
        session = sessions.create(summary_id)
        _, _, turn = _add_turn(
            connection,
            session.id,
            user_text=text,
            assistant_text="reply",
        )
        _insert_summary(
            connection,
            session_id=session.id,
            turn=turn,
            summary_id=summary_id,
            text=text,
            updated_at=updated_at,
        )
        expected.append(summary_id)
    authority = _grant(connection, _policy(max_fragments=4))

    selected = _selector(connection).select(
        active_session_id=active.id,
        current_user_text="红茶计划",
        selected_recent_message_ids=(),
        authority=authority,
    )

    assert [fragment.summary_id for fragment in selected.fragments] == [
        "score-high",
        "later-a",
        "later-b",
        "older",
    ]


@pytest.mark.parametrize(
    "invalid_kind",
    [
        "manual",
        "redacted",
        "quarantined",
        "legacy",
        "stale_barrier",
        "excluded",
        "missing_message",
        "unsupported_summarizer",
        "unsupported_injection",
        "suppressed",
        "oversized",
        "credential_payload",
        "corrupt_metadata",
        "incomplete_source_map",
    ],
)
def test_ineligible_summary_rows_are_rejected(
    connection: sqlite3.Connection,
    invalid_kind: str,
) -> None:
    session = SessionRepository(connection).create(invalid_kind)
    _, _, turn = _add_turn(
        connection,
        session.id,
        user_text="红茶计划",
        assistant_text="继续讨论",
    )
    policy = _policy(max_fragment_characters=20)
    kwargs: dict[str, object] = {
        "source": "manual" if invalid_kind == "manual" else "generated",
        "payload_state": (
            invalid_kind
            if invalid_kind in {"redacted", "quarantined"}
            else "active"
        ),
        "provenance_state": (
            "legacy_unverified" if invalid_kind == "legacy" else "exact"
        ),
        "summarizer_schema": (
            "unsupported-summary-schema"
            if invalid_kind == "unsupported_summarizer"
            else SUMMARY_SCHEMA_VERSION
        ),
        "injection_schema": (
            "unsupported-injection-schema"
            if invalid_kind == "unsupported_injection"
            else SUMMARY_INJECTION_SCHEMA_VERSION
        ),
        "observed_barrier": 1 if invalid_kind == "stale_barrier" else 0,
        "metadata_json": "not-json" if invalid_kind == "corrupt_metadata" else "{}",
    }
    text = None if invalid_kind in {"redacted", "quarantined"} else "红茶计划"
    if invalid_kind == "oversized":
        text = "红茶计划" * 10
    elif invalid_kind == "credential_payload":
        text = "api_key=sk-secret-value"
    source_hash, user_id, assistant_id = _insert_summary(
        connection,
        session_id=session.id,
        turn=turn,
        summary_id=f"invalid-{invalid_kind}",
        text=text,
        updated_at=datetime.now(UTC),
        retain_covered_message_ids=invalid_kind != "missing_message",
        **kwargs,  # type: ignore[arg-type]
    )
    if invalid_kind == "excluded":
        connection.execute(
            "INSERT INTO memory_summary_source_exclusions "
            "(source_message_id, reason_code, created_at) VALUES (?, ?, ?)",
            (user_id, "fixture", datetime.now(UTC).isoformat()),
        )
    elif invalid_kind == "missing_message":
        connection.execute("DELETE FROM messages WHERE id=?", (assistant_id,))
    elif invalid_kind == "suppressed":
        connection.execute(
            """
            INSERT INTO summary_source_suppressions (
                session_id, source_set_hash, generation, state,
                rebuild_permit_id, bound_job_id, authorized_summary_id,
                reason_code, created_at, updated_at
            ) VALUES (?, ?, 1, 'suppressed', NULL, NULL, NULL, 'fixture', ?, ?)
            """,
            (
                session.id,
                source_hash,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
    elif invalid_kind == "incomplete_source_map":
        connection.execute(
            "DELETE FROM session_summary_sources "
            "WHERE summary_id=? AND message_order_in_turn=1",
            (f"invalid-{invalid_kind}",),
        )
    connection.commit()
    authority = _grant(connection, policy)

    selected = _selector(connection).select(
        active_session_id="different-active-session",
        current_user_text="红茶计划",
        selected_recent_message_ids=(),
        authority=authority,
    )

    assert selected.fragments == ()


def test_missing_or_stale_injection_authority_selects_nothing(
    connection: sqlite3.Connection,
) -> None:
    session = SessionRepository(connection).create("authority")
    _, _, turn = _add_turn(
        connection,
        session.id,
        user_text="红茶计划",
        assistant_text="继续讨论",
    )
    _insert_summary(
        connection,
        session_id=session.id,
        turn=turn,
        summary_id="eligible",
        text="红茶计划",
        updated_at=datetime.now(UTC),
    )
    policy = _policy()
    authority = _grant(connection, policy)
    selector = _selector(connection)

    assert selector.select(
        active_session_id=session.id,
        current_user_text="红茶计划",
        selected_recent_message_ids=(),
        authority=None,
    ).fragments == ()

    SummaryAutomationRepository(connection).mutate_injection(
        action="revoke",
        expected_generation=authority.generation,
        policy=policy,
    )
    stale = selector.select(
        active_session_id=session.id,
        current_user_text="红茶计划",
        selected_recent_message_ids=(),
        authority=authority,
    )
    assert stale.fragments == ()
    assert stale.authority is None


def test_fragment_count_is_frozen_by_authority(
    connection: sqlite3.Connection,
) -> None:
    sessions = SessionRepository(connection)
    for index in range(3):
        session = sessions.create(f"session-{index}")
        _, _, turn = _add_turn(
            connection,
            session.id,
            user_text="红茶计划",
            assistant_text="继续",
        )
        _insert_summary(
            connection,
            session_id=session.id,
            turn=turn,
            summary_id=f"summary-{index}",
            text="红茶计划",
            updated_at=datetime.now(UTC) + timedelta(seconds=index),
        )
    authority = _grant(connection, _policy(max_fragments=2))

    selected = _selector(connection).select(
        active_session_id="different-active-session",
        current_user_text="红茶计划",
        selected_recent_message_ids=(),
        authority=authority,
    )

    assert len(selected.fragments) == 2
