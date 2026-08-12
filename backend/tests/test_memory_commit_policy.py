import json
from pathlib import Path

import pytest

from app.domain.models import (
    MemoryGovernorDecision,
    MemoryGovernorProposal,
    MemoryType,
    MemoryWriteActivityOutcome,
)
from app.services.memory_commit_policy import (
    MemoryCommitPolicy,
    MemoryCommitTarget,
    canonicalize_memory_v1,
    proposal_fingerprint_v1,
    verify_explicit_user_assertion,
)
from app.services.memory_gate_b_contract import (
    MEMORY_CANONICALIZATION_VERSION,
    MEMORY_GATE_B_FIXTURE_SCHEMA_VERSION,
)
from app.services.memory_governor import MemoryGovernor
from app.services.relationship_contract import canonical_relationship_subject_code


_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "memory_gate_b" / "commit_cases.json"
)


def _proposal(
    *,
    memory_type: MemoryType,
    subject: str,
    content: str,
    source_message_ids: tuple[str, ...] = ("user-1",),
    confidence: float = 0.9,
    canonical_key_hint: str | None = None,
) -> MemoryGovernorProposal:
    return MemoryGovernorProposal(
        memory_type=memory_type,
        subject=subject,
        content=content,
        canonical_key_hint=canonical_key_hint,
        confidence=confidence,
        source_message_ids=source_message_ids,
    )


def _governor() -> MemoryGovernor:
    return MemoryGovernor(
        max_proposals=5,
        max_proposal_characters=300,
        max_total_characters=1000,
    )


def _target(
    memory_id: str,
    *,
    memory_type: MemoryType,
    subject: str,
    content: str,
    open_conflict: bool = False,
) -> MemoryCommitTarget:
    canonical = canonicalize_memory_v1(
        memory_type=memory_type,
        subject=subject,
        content=content,
    )
    return MemoryCommitTarget(
        memory_id=memory_id,
        memory_type=memory_type,
        content=canonical.normalized_content,
        canonical_key_hash=canonical.canonical_key_hash,
        subject_key_hash=canonical.subject_key_hash,
        current_version_id=f"{memory_id}-v1",
        head_version=1,
        record_generation=0,
        open_conflict=open_conflict,
    )


def _evaluate(
    proposal: MemoryGovernorProposal,
    *,
    user_text: str,
    current_heads: tuple[MemoryCommitTarget, ...] = (),
    tombstone_match: str | None = None,
):
    governor_result = _governor().evaluate(
        proposal=proposal,
        user_text=user_text,
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    return MemoryCommitPolicy().evaluate(
        proposal=proposal,
        governor_result=governor_result,
        user_text=user_text,
        user_message_id="user-1",
        current_heads=current_heads,
        tombstone_match=tombstone_match,
    )


def test_automatic_proposal_text_never_maps_to_relationship_classification() -> None:
    suspicious_values = (
        "preferred_address",
        "称呼偏好",
        "preferred_address:小雪",
        "请以后叫用户小雪",
        "summary: 用户希望称呼为小雪",
        "喜欢亲密称呼",
    )

    for value in suspicious_values:
        proposal = MemoryGovernorProposal(
            memory_type=MemoryType.PREFERENCE,
            subject=value,
            content=value,
            canonical_key_hint=value,
            confidence=0.99,
            source_message_ids=("user-1",),
        )
        assert canonical_relationship_subject_code(
            memory_type=proposal.memory_type,
            explicit_subject_code=None,
        ) is None
        assert not hasattr(proposal, "canonical_subject_code")


def test_canonicalization_v1_uses_frozen_unicode_pipeline_and_hashes() -> None:
    first = canonicalize_memory_v1(
        memory_type=MemoryType.PREFERENCE,
        subject=" ＤＲＩＮＫ​   Pref ",
        content=" I⁠   LIKE  COFFEE ",
    )
    second = canonicalize_memory_v1(
        memory_type=MemoryType.PREFERENCE,
        subject="drink pref",
        content="i like coffee",
    )

    assert first == second
    assert first.canonicalization_version == MEMORY_CANONICALIZATION_VERSION
    assert len(first.canonical_key_hash) == 64
    assert len(first.subject_key_hash) == 64


def test_canonicalization_uses_ascii_lower_only() -> None:
    canonical = canonicalize_memory_v1(
        memory_type=MemoryType.OTHER,
        subject="ÄBCΣ",
        content="ÄBCΣ",
    )

    assert canonical.normalized_subject == "ÄbcΣ"
    assert canonical.normalized_content == "ÄbcΣ"


def test_governor_and_commit_policy_share_canonicalization() -> None:
    proposal = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject=" ＤＲＩＮＫ​   Pref ",
        content=" I⁠   LIKE  COFFEE ",
    )
    governor_result = _governor().evaluate(
        proposal=proposal,
        user_text="I LIKE COFFEE",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    canonical = canonicalize_memory_v1(
        memory_type=proposal.memory_type,
        subject=proposal.subject,
        content=proposal.content,
    )

    assert governor_result.canonical_key == canonical.canonical_key_hash


def test_proposal_fingerprint_is_stable_across_hint_and_source_order() -> None:
    first = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject="饮品偏好",
        content="用户喜欢无糖茶",
        source_message_ids=("user-1", "assistant-1"),
        canonical_key_hint="remote-one",
    )
    second = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject=" 饮品偏好 ",
        content="用户喜欢无糖茶",
        source_message_ids=("assistant-1", "user-1"),
        canonical_key_hint="remote-two",
    )

    assert proposal_fingerprint_v1(proposal=first) == proposal_fingerprint_v1(
        proposal=second
    )


def test_proposal_fingerprint_changes_with_validated_semantics() -> None:
    base = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject="饮品偏好",
        content="用户喜欢无糖茶",
    )
    changed = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject="饮品偏好",
        content="用户不喜欢无糖茶",
    )

    assert proposal_fingerprint_v1(proposal=base) != proposal_fingerprint_v1(
        proposal=changed
    )


@pytest.mark.parametrize(
    ("user_text", "proposal"),
    [
        (
            "我长期喜欢晨间散步。",
            _proposal(
                memory_type=MemoryType.PREFERENCE,
                subject="晨间活动偏好",
                content="用户喜欢晨间散步",
            ),
        ),
        (
            "我从来不喝咖啡。",
            _proposal(
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户不喜欢咖啡",
            ),
        ),
        (
            "更正一下，我现在住在海边城市。",
            _proposal(
                memory_type=MemoryType.USER_FACT,
                subject="居住地",
                content="用户住在海边城市",
            ),
        ),
    ],
)
def test_grounding_accepts_only_frozen_explicit_user_assertions(
    user_text: str,
    proposal: MemoryGovernorProposal,
) -> None:
    assert verify_explicit_user_assertion(
        proposal=proposal,
        user_text=user_text,
        user_message_id="user-1",
    )


def test_grounding_rejects_assistant_invention_and_wrong_source() -> None:
    invented = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject="放松偏好",
        content="用户喜欢用园艺放松",
        source_message_ids=("user-1", "assistant-1"),
    )
    wrong_source = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject="放松偏好",
        content="用户喜欢用园艺放松",
        source_message_ids=("assistant-1",),
    )

    assert not verify_explicit_user_assertion(
        proposal=invented,
        user_text="今天有点累。",
        user_message_id="user-1",
    )
    assert not verify_explicit_user_assertion(
        proposal=wrong_source,
        user_text="我喜欢用园艺放松。",
        user_message_id="user-1",
    )


def test_commit_policy_fixture_cases_in_task_6_scope() -> None:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["fixture_schema_version"] == MEMORY_GATE_B_FIXTURE_SCHEMA_VERSION
    cases = {case["name"]: case for case in fixture["cases"]}

    proposals = {
        "safe_create": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="晨间活动偏好",
            content="用户喜欢晨间散步",
        ),
        "exact_support": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢无糖茶",
        ),
        "explicit_correction": _proposal(
            memory_type=MemoryType.USER_FACT,
            subject="居住地",
            content="用户住在海边城市",
        ),
        "unique_conflict": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户不喜欢咖啡",
        ),
        "ambiguous_exact": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="阅读偏好",
            content="用户喜欢阅读科幻小说",
        ),
        "ambiguous_conflict": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户不喜欢热饮",
        ),
        "sensitive_reject": _proposal(
            memory_type=MemoryType.OTHER,
            subject="测试密码",
            content="用户的测试密码是 example-secret-value",
        ),
        "explicit_no_memory": _proposal(
            memory_type=MemoryType.OTHER,
            subject="随口内容",
            content="用户接下来随口说的内容",
        ),
        "deletion_intent": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="旧爱好",
            content="用户有旧爱好",
        ),
        "assistant_invented_fact": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="放松偏好",
            content="用户喜欢用园艺放松",
            source_message_ids=("user-1", "assistant-1"),
        ),
        "exact_tombstone": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="收藏偏好",
            content="用户喜欢收集明信片",
        ),
        "subject_tombstone": _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户偏好花草茶",
        ),
    }
    heads = {
        "exact_support": (
            _target(
                "tea",
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户喜欢无糖茶",
            ),
        ),
        "explicit_correction": (
            _target(
                "residence",
                memory_type=MemoryType.USER_FACT,
                subject="居住地",
                content="用户住在山城",
            ),
        ),
        "unique_conflict": (
            _target(
                "coffee",
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户喜欢咖啡",
            ),
        ),
        "ambiguous_exact": (
            _target(
                "science-fiction-1",
                memory_type=MemoryType.PREFERENCE,
                subject="阅读偏好",
                content="用户喜欢阅读科幻小说",
            ),
            _target(
                "science-fiction-2",
                memory_type=MemoryType.PREFERENCE,
                subject="阅读偏好",
                content="用户喜欢阅读科幻小说",
            ),
        ),
        "ambiguous_conflict": (
            _target(
                "hot-tea",
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户喜欢热茶",
            ),
            _target(
                "hot-cocoa",
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户喜欢热可可",
            ),
        ),
    }
    tombstones = {
        "exact_tombstone": "exact_canonical_key",
        "subject_tombstone": "subject_key",
    }

    for name, proposal in proposals.items():
        result = _evaluate(
            proposal,
            user_text=cases[name]["user_text"],
            current_heads=heads.get(name, ()),
            tombstone_match=tombstones.get(name),
        )
        assert result.classification == cases[name]["expected_decision"], name
        if name in {"sensitive_reject", "explicit_no_memory", "deletion_intent"}:
            assert result.decision is MemoryGovernorDecision.REJECT
            assert (
                result.outcome
                is MemoryWriteActivityOutcome.REJECTED_GOVERNOR_POLICY
            )

    assert {
        "stale_user_edit",
        "deleted_job",
        "dual_consent",
    } <= set(cases) - set(proposals)


def test_governor_rejections_use_normal_policy_outcome_not_failure() -> None:
    proposal = _proposal(
        memory_type=MemoryType.OTHER,
        subject="随口内容",
        content="用户接下来随口说的内容",
    )
    result = _evaluate(
        proposal,
        user_text="不要记住我接下来随口说的内容。",
    )

    assert result.decision is MemoryGovernorDecision.REJECT
    assert result.outcome is MemoryWriteActivityOutcome.REJECTED_GOVERNOR_POLICY
    assert result.outcome is not MemoryWriteActivityOutcome.FAILED
    assert result.reason_code == "explicit_no_memory"


def test_commit_policy_blocks_open_conflict_target() -> None:
    proposal = _proposal(
        memory_type=MemoryType.PREFERENCE,
        subject="饮品偏好",
        content="用户不喜欢咖啡",
    )
    result = _evaluate(
        proposal,
        user_text="我不喜欢咖啡。",
        current_heads=(
            _target(
                "coffee",
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户喜欢咖啡",
                open_conflict=True,
            ),
        ),
    )

    assert result.decision is MemoryGovernorDecision.REJECT
    assert result.outcome is MemoryWriteActivityOutcome.BLOCKED_OPEN_CONFLICT
    assert result.target is None


def test_commit_policy_requires_explicit_correction_for_supersede() -> None:
    proposal = _proposal(
        memory_type=MemoryType.USER_FACT,
        subject="居住地",
        content="用户住在海边城市",
    )
    target = _target(
        "residence",
        memory_type=MemoryType.USER_FACT,
        subject="居住地",
        content="用户住在山城",
    )

    ordinary = _evaluate(
        proposal,
        user_text="我住在海边城市。",
        current_heads=(target,),
    )
    correction = _evaluate(
        proposal,
        user_text="更正一下，我现在住在海边城市。",
        current_heads=(target,),
    )

    assert ordinary.decision is MemoryGovernorDecision.CONFLICT
    assert correction.decision is MemoryGovernorDecision.SUPERSEDE
    assert correction.target == target
