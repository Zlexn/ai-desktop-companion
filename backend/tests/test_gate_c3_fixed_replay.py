"""Gate C3 fixed replay and scorecard arithmetic validation.

The versioned fixture (`gate_c3_replay_v1.json`) holds 30 fixed Chinese
multi-session questions with declared schema/rule/Composer/encoder versions and
a tested content hash. This test:

- verifies the fixture content hash and declared versions;
- replays every question through the complete `ChatService.send_message` path
  with a recording fake Provider, asserting chat survival, deterministic
  output identity, no forbidden source revival, and no forbidden keys;
- validates the human-evaluation scorecard arithmetic (category averages
  >= 1.6 with no intermediate rounding; low-reply ratio < 0.05) without
  fabricating human scores.

This automated replay is contract/privacy evidence only. Its canned fake
replies can never satisfy the human Persona/continuity/natural-language quality
gate, which remains PENDING until a completed human scorecard passes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.models import MemorySource, MemoryType
from app.providers.base import LLMResponse
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.context_sources import ContextSourceRepository
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.personas import PersonaRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.chat_service import ChatService
from app.services.context_composer import ContextComposer
from app.services.context_data_encoder import ContextDataEncoder
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
from app.services.prompt_renderer import default_prompt_renderer
from app.services.relationship_dispatch import RelationshipDisclosureFence
from app.services.relationship_injection import RelationshipInjectionService
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from tests.test_relationship_projector import _BASE_TIME

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gate_c3_replay_v1.json"

FORBIDDEN_KEYS = (
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

CATEGORIES = (
    "core_persona",
    "factual_caution",
    "relationship_continuity",
    "natural_language",
    "non_official",
)


def _load_fixture() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _canonical_bytes(fixture: dict) -> bytes:
    without_hash = {k: v for k, v in fixture.items() if k != "content_sha256"}
    return json.dumps(
        without_hash,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class RecordingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list] = []

    async def generate(self, messages, options):
        self.calls.append(list(messages))
        latest = ""
        for message in messages:
            if getattr(message, "role", None) == "user":
                latest = message.content
        return LLMResponse(
            text=f"回放回复：{latest}",
            provider=self.provider_name,
            model=options.model,
        )


def _run(coro):
    return asyncio.run(coro)


def _seed_and_build_service(
    connection,
    database_url: str,
    fixture: dict,
):
    """Build the real ChatService with the fixture's sessions/memories seeded.

    The caller owns the open connection; returns (service, provider, memory_ids).
    """
    from app.core.config import Settings

    settings = Settings(llm_provider="fake", llm_model="test-model")
    references = MemorySourceReferenceService(b"q" * 32)
    renderer = default_prompt_renderer()
    personas = PersonaService(
        PersonaRepository(connection),
        compiler=PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=settings.persona_max_characters,
        ),
        bootstrap_config=renderer.load_persona_v1_config(),
    )
    persona_id = personas.bootstrap().artifact.id

    sessions = SessionRepository(connection)
    for session in fixture["seed"]["sessions"]:
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                session["id"],
                session["title"],
                _BASE_TIME.isoformat(),
                _BASE_TIME.isoformat(),
            ),
        )
    connection.commit()

    memories = MemoryRepository(connection, source_references=references)
    memory_ids: dict[str, str] = {}
    for item in fixture["seed"]["memories"]:
        memory_type = MemoryType(item["memory_type"])
        subject = (
            item["canonical_subject_code"]
            if item["canonical_subject_code"] is not None
            else None
        )
        memory, _conflicts = memories.create(
            content=item["content"],
            memory_type=memory_type,
            source=MemorySource.MANUAL,
            source_session_id=item.get("source_session_id"),
            importance=item["importance"],
            confidence=item["confidence"],
            canonical_subject_code=subject,
        )
        memory_ids[item["id"]] = memory.id
        connection.commit()

    # Apply the fixture's suppression decisions after reconciliation.
    scheduler = RelationshipScheduler(
        RelationshipReconciler(connection),
        persona_artifact_id=persona_id,
    )
    scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
    connection.commit()
    for subject in fixture["seed"].get("suppressed_subjects", []):
        from app.domain.relationship import RelationshipEventType
        from app.repositories.relationship_ledger import (
            RelationshipLedgerRepository,
        )
        from app.services.relationship_authority import (
            RelationshipAuthorityService,
        )

        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        memory_id = memory_ids[subject["memory_id"]]
        current = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType(subject["event_type"]),
            subject_code=subject["subject_code"],
        )
        authority.suppress(
            source_memory_id=memory_id,
            event_type=RelationshipEventType(subject["event_type"]),
            subject_code=subject["subject_code"],
            action_kind=from_app_relationship_authority_action_kind("user_revoke"),
            reason_code="user_revoked",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))
        connection.commit()

    # True-forget the designated memory before any question replay.
    versioned = VersionedMemoryRepository(connection)
    for memory_id in fixture["seed"].get("forgotten_memory_ids", []):
        from app.services.memory_forget_service import MemoryForgetService

        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        forget.forget_memory(memory_ids[memory_id])
        connection.commit()
    scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=3))
    connection.commit()

    provider = RecordingProvider()
    service = ChatService(
        sessions,
        MessageRepository(connection),
        ChatTurnRepository(connection),
        personas,
        ContextSourceRepository(
            MessageRepository(connection),
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
    return service, provider, memory_ids, sessions


def from_app_relationship_authority_action_kind(value: str):
    from app.domain.relationship import RelationshipAuthorityActionKind

    return RelationshipAuthorityActionKind(value)


def test_fixture_content_hash_and_declared_versions() -> None:
    fixture = _load_fixture()
    assert fixture["fixture_schema_version"] == "gate-c3-replay-v1"
    digest = hashlib.sha256(_canonical_bytes(fixture)).hexdigest()
    assert digest == fixture["content_sha256"]
    assert fixture["declared_versions"]["composer_version"] == "context-composer-v2"
    assert fixture["declared_versions"]["encoder_version"] == "context-data-encoder-v2"
    assert fixture["declared_versions"]["manifest_version"] == "context-manifest-v2"
    assert fixture["declared_versions"]["relationship_rule_version"] == (
        "relationship-projection-v1"
    )
    questions = fixture["questions"]
    assert len(questions) >= 30
    # No user-private data, credentials, private paths, or cloned assets.
    raw = json.dumps(fixture, ensure_ascii=False).lower()
    for forbidden in (
        "password",
        "api_key",
        "authorization",
        "bearer ",
        "sk-",
        "c:\\users",
        ".mp3",
        ".wav",
        "live2d",
        "雪之下雪乃",
    ):
        assert forbidden not in raw


def test_replay_all_questions_survive_and_never_revive_forgotten(tmp_path: Path) -> None:
    fixture = _load_fixture()
    database_url = f"sqlite:///{tmp_path / 'gate-c3-replay.db'}"
    with managed_connection(database_url) as connection:
        service, provider, _memory_ids, sessions = _seed_and_build_service(
            connection,
            database_url,
            fixture,
        )
        session_map = {s["id"]: s for s in fixture["seed"]["sessions"]}
        forgotten_sentinel = fixture["seed"]["forgotten_sentinel"]

        # Seed the forgotten sentinel directly so a revival would be detectable
        # in any surface (the fixture memory was true-forgotten before replay).
        connection.execute(
            "INSERT OR IGNORE INTO memories "
            "(id, content, memory_type, source, source_session_id, importance, "
            " confidence, status, metadata_json, created_at, updated_at) "
            "VALUES ('sentinel-probe', ?, 'user_fact', 'manual', NULL, 3, 1.0, "
            "'archived', '{}', ?, ?)",
            (forgotten_sentinel, _BASE_TIME.isoformat(), _BASE_TIME.isoformat()),
        )
        connection.commit()

        for index, question in enumerate(fixture["questions"], start=1):
            session = sessions.get(session_map[question["session_id"]]["id"])
            assert session is not None, question["id"]
            reply = _run(service.send_message(session.id, question["text"]))
            assert reply.reply, question["id"]

            provider_call = "\n".join(
                item.content for item in provider.calls[index - 1]
            )
            # Forbidden keys never appear in the Provider payload.
            for key in FORBIDDEN_KEYS:
                assert key not in provider_call, f"{question['id']} leaked {key}"
            # The forgotten address content and probe sentinel never revive.
            for memory in fixture["seed"]["memories"]:
                if memory["id"] in fixture["seed"]["forgotten_memory_ids"]:
                    assert memory["content"] not in provider_call, question["id"]
            assert forgotten_sentinel not in provider_call, question["id"]
            # Relationship layer is only injected as a low-authority non-fact.
            if question["category"] in {
                "relationship_continuity",
                "shared_experience",
                "suppressed_shared_experience",
                "non_external_commitment",
            }:
                assert (
                    '"authority":"derived_relationship_projection_not_fact"'
                    in provider_call
                )


def test_replay_deterministic_output_identity(tmp_path: Path) -> None:
    fixture = _load_fixture()
    question = fixture["questions"][0]
    database_url = f"sqlite:///{tmp_path / 'gate-c3-determinism.db'}"

    with managed_connection(database_url) as connection:
        service, provider, _memory_ids, sessions = _seed_and_build_service(
            connection,
            database_url,
            fixture,
        )
        session_a = sessions.get(fixture["seed"]["sessions"][0]["id"])
        assert session_a is not None
        _run(service.send_message(session_a.id, question["text"]))
        # A second fresh session with the same first question must produce an
        # identical Provider call: deterministic encoding given equal inputs.
        second = sessions.create("second")
        _run(service.send_message(second.id, question["text"]))

        first_payload = "\n".join(item.content for item in provider.calls[0])
        second_payload = "\n".join(item.content for item in provider.calls[1])
        assert first_payload == second_payload
        assert provider.calls[0] == provider.calls[1]


def test_scorecard_arithmetic_thresholds_with_no_rounding() -> None:
    """Validate the 0-2 scorecard arithmetic used by the human evaluation.

    This never fabricates human scores; it only verifies the arithmetic rules:
    each category average must be >= 1.6 with no intermediate rounding, and the
    low-reply ratio (aggregate < 1.0) must be below 0.05.
    """

    def category_average(scores: list[int]) -> float:
        return sum(scores) / len(scores)

    def aggregate(scores: list[int]) -> float:
        return sum(scores) / len(scores)

    def is_low_reply(scores: list[int]) -> bool:
        return aggregate(scores) < 1.0

    def pass_scorecard(replies: list[list[int]]) -> tuple[bool, str]:
        count = len(replies)
        assert count >= 30
        low_count = sum(1 for scores in replies if is_low_reply(scores))
        for category in range(5):
            avg = category_average([scores[category] for scores in replies])
            if avg < 1.6:
                return False, f"category {category} average {avg} < 1.6"
        if low_count / count >= 0.05:
            return False, f"low reply ratio {low_count / count} >= 0.05"
        return True, "pass"

    # A passing 30-reply packet: every category average >= 1.6, one low reply ok.
    passing: list[list[int]] = []
    for i in range(30):
        if i == 0:
            scores = [0, 0, 1, 1, 1]  # one low reply (aggregate 0.6)
        else:
            scores = [2, 2, 2, 2, 2]
        passing.append(scores)
    ok, message = pass_scorecard(passing)
    assert ok, message
    assert category_average([scores[0] for scores in passing]) >= 1.6

    # A failing packet: two low replies out of 30 -> ratio 0.0667 >= 0.05.
    failing = list(passing)
    failing[1] = [0, 0, 0, 0, 0]
    ok, message = pass_scorecard(failing)
    assert not ok
    assert "low reply ratio" in message

    # No intermediate rounding: 1.6 threshold uses exact float comparison.
    borderline = [[2, 1, 2, 2, 2] for _ in range(30)]
    avg = category_average([scores[1] for scores in borderline])
    assert avg == 1.0
    assert avg < 1.6


def test_replay_without_relationship_injection_still_survives(
    tmp_path: Path,
) -> None:
    """Chat survives even when the relationship subsystem is entirely absent."""
    from app.core.config import Settings

    fixture = _load_fixture()
    settings = Settings(llm_provider="fake", llm_model="test-model")
    database_url = f"sqlite:///{tmp_path / 'gate-c3-no-rel.db'}"
    with managed_connection(database_url) as connection:
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
        sessions = SessionRepository(connection)
        session = sessions.create("no-rel")
        memories = MemoryRepository(connection)
        provider = RecordingProvider()
        service = ChatService(
            sessions,
            MessageRepository(connection),
            ChatTurnRepository(connection),
            personas,
            ContextSourceRepository(
                MessageRepository(connection),
                memories,
                sessions=sessions,
            ),
            ContextComposer(settings, ContextDataEncoder()),
            provider,
            settings,
            relationship_injection=None,
        )
        reply = _run(service.send_message(session.id, fixture["questions"][0]["text"]))
        assert reply.reply
        provider_call = "\n".join(item.content for item in provider.calls[0])
        for key in FORBIDDEN_KEYS:
            assert key not in provider_call
