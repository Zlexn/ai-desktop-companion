from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence

from app.domain.models import (
    MemoryGovernorDecision,
    MemoryGovernorProposal,
    MemoryGovernorResult,
    MemoryType,
    MemoryWriteActivityOutcome,
)
from app.repositories.memories import (
    _semantic_conflict,
    _semantic_signature,
)
from app.services.memory_gate_b_contract import MEMORY_CANONICALIZATION_VERSION


_ASCII_UPPER_TO_LOWER = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
)


@dataclass(frozen=True)
class CanonicalMemoryV1:
    memory_type: MemoryType
    normalized_subject: str
    normalized_content: str
    canonical_key_hash: str
    subject_key_hash: str
    content_key_hash: str
    canonicalization_version: str = MEMORY_CANONICALIZATION_VERSION


@dataclass(frozen=True)
class MemoryCommitTarget:
    memory_id: str
    memory_type: MemoryType
    content: str
    canonical_key_hash: str | None
    subject_key_hash: str | None
    current_version_id: str
    head_version: int
    record_generation: int
    open_conflict: bool = False


@dataclass(frozen=True)
class TargetSelection:
    target: MemoryCommitTarget | None
    ambiguous: bool


@dataclass(frozen=True)
class ExplicitUserAssertion:
    memory_type: MemoryType
    content: str
    explicit_correction: bool


@dataclass(frozen=True)
class MemoryCommitPolicyResult:
    decision: MemoryGovernorDecision
    outcome: MemoryWriteActivityOutcome
    reason_code: str
    target: MemoryCommitTarget | None
    canonical: CanonicalMemoryV1 | None
    proposal_fingerprint: str | None

    @property
    def classification(self) -> str:
        if self.decision in {
            MemoryGovernorDecision.CREATE,
            MemoryGovernorDecision.SUPPORT,
            MemoryGovernorDecision.SUPERSEDE,
            MemoryGovernorDecision.CONFLICT,
        }:
            return self.decision.value
        if self.outcome is MemoryWriteActivityOutcome.REJECTED_GOVERNOR_POLICY:
            return self.decision.value
        return self.outcome.value


def normalize_memory_text_v1(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )
    normalized = " ".join(normalized.split())
    return normalized.translate(_ASCII_UPPER_TO_LOWER)


def _sha256(material: str) -> str:
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def canonicalize_memory_v1(
    *,
    memory_type: MemoryType,
    subject: str,
    content: str,
) -> CanonicalMemoryV1:
    if type(memory_type) is not MemoryType:
        raise ValueError("memory_type must be a MemoryType")
    if not isinstance(subject, str) or not isinstance(content, str):
        raise ValueError("subject and content must be strings")
    normalized_subject = normalize_memory_text_v1(subject)
    normalized_content = normalize_memory_text_v1(content)
    if not normalized_subject or not normalized_content:
        raise ValueError("subject and content must be non-empty")
    return CanonicalMemoryV1(
        memory_type=memory_type,
        normalized_subject=normalized_subject,
        normalized_content=normalized_content,
        canonical_key_hash=_sha256(
            f"{memory_type.value}:{normalized_subject}:{normalized_content}"
        ),
        subject_key_hash=_sha256(f"{memory_type.value}:{normalized_subject}"),
        content_key_hash=_sha256(f"{memory_type.value}:{normalized_content}"),
    )


def proposal_fingerprint_v1(*, proposal: MemoryGovernorProposal) -> str:
    canonical = canonicalize_memory_v1(
        memory_type=proposal.memory_type,
        subject=proposal.subject,
        content=proposal.content,
    )
    source_message_ids = proposal.source_message_ids
    if (
        not isinstance(source_message_ids, tuple)
        or not source_message_ids
        or any(not isinstance(source_id, str) or not source_id for source_id in source_message_ids)
        or len(set(source_message_ids)) != len(source_message_ids)
    ):
        raise ValueError("source_message_ids must be a unique non-empty string tuple")
    if isinstance(proposal.confidence, bool) or not isinstance(
        proposal.confidence,
        (int, float),
    ):
        raise ValueError("confidence must be numeric")
    material = json.dumps(
        {
            "canonicalization_version": MEMORY_CANONICALIZATION_VERSION,
            "memory_type": proposal.memory_type.value,
            "normalized_subject": canonical.normalized_subject,
            "normalized_content": canonical.normalized_content,
            "confidence": float(proposal.confidence),
            "source_message_ids": sorted(source_message_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(material)


def _strip_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip("。！？!?；;").strip()


def _explicit_user_assertion(user_text: str) -> ExplicitUserAssertion | None:
    text = _strip_terminal_punctuation(normalize_memory_text_v1(user_text))
    patterns: tuple[
        tuple[re.Pattern[str], MemoryType, str, bool],
        ...,
    ] = (
        (
            re.compile(r"^更正一下[，,]?我现在住在(?P<value>.+)$"),
            MemoryType.USER_FACT,
            "用户住在{value}",
            True,
        ),
        (
            re.compile(r"^我现在住在(?P<value>.+)$"),
            MemoryType.USER_FACT,
            "用户住在{value}",
            True,
        ),
        (
            re.compile(r"^我住在(?P<value>.+)$"),
            MemoryType.USER_FACT,
            "用户住在{value}",
            False,
        ),
        (
            re.compile(r"^我叫\s*(?P<value>.+)$"),
            MemoryType.USER_FACT,
            "用户叫{value}",
            False,
        ),
        (
            re.compile(r"^我(?:长期|还是)?喜欢(?P<value>.+)$"),
            MemoryType.PREFERENCE,
            "用户喜欢{value}",
            False,
        ),
        (
            re.compile(r"^我不喜欢(?P<value>.+)$"),
            MemoryType.PREFERENCE,
            "用户不喜欢{value}",
            False,
        ),
        (
            re.compile(r"^我从来不喝(?P<value>.+)$"),
            MemoryType.PREFERENCE,
            "用户不喜欢{value}",
            False,
        ),
        (
            re.compile(r"^我的饮品偏好是(?P<value>.+)$"),
            MemoryType.PREFERENCE,
            "用户偏好{value}",
            False,
        ),
        (
            re.compile(r"^我的目标是(?P<value>.+)$"),
            MemoryType.LONG_TERM_GOAL,
            "用户的目标是{value}",
            False,
        ),
        (
            re.compile(r"^我计划(?P<value>.+)$"),
            MemoryType.LONG_TERM_GOAL,
            "用户计划{value}",
            False,
        ),
    )
    for pattern, memory_type, template, explicit_correction in patterns:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        value = _strip_terminal_punctuation(match.group("value"))
        if value:
            return ExplicitUserAssertion(
                memory_type=memory_type,
                content=normalize_memory_text_v1(template.format(value=value)),
                explicit_correction=explicit_correction,
            )
    return None


def verify_explicit_user_assertion(
    *,
    proposal: MemoryGovernorProposal,
    user_text: str,
    user_message_id: str,
) -> bool:
    if user_message_id not in proposal.source_message_ids:
        return False
    assertion = _explicit_user_assertion(user_text)
    if assertion is None or assertion.memory_type is not proposal.memory_type:
        return False
    return assertion.content == normalize_memory_text_v1(proposal.content)


def select_unique_exact_target(
    *,
    eligible_records: Sequence[MemoryCommitTarget],
    canonical_key_hash: str,
    memory_type: MemoryType | None = None,
    normalized_content: str | None = None,
) -> TargetSelection:
    matches = [
        record
        for record in eligible_records
        if record.canonical_key_hash == canonical_key_hash
        or (
            record.canonical_key_hash is None
            and memory_type is not None
            and normalized_content is not None
            and record.memory_type is memory_type
            and normalize_memory_text_v1(record.content) == normalized_content
        )
    ]
    return TargetSelection(
        target=matches[0] if len(matches) == 1 else None,
        ambiguous=len(matches) > 1,
    )


def _target_semantically_conflicts(
    proposal: MemoryGovernorProposal,
    target: MemoryCommitTarget,
) -> bool:
    if target.memory_type is not proposal.memory_type:
        return False
    return _semantic_conflict(
        _semantic_signature(proposal.content, proposal.memory_type),
        _semantic_signature(target.content, target.memory_type),
        proposal.memory_type,
    )


def select_unique_conflict_target(
    *,
    proposal: MemoryGovernorProposal,
    eligible_records: Sequence[MemoryCommitTarget],
) -> TargetSelection:
    matches = [
        record
        for record in eligible_records
        if _target_semantically_conflicts(proposal, record)
    ]
    return TargetSelection(
        target=matches[0] if len(matches) == 1 else None,
        ambiguous=len(matches) > 1,
    )


def _rejected_result(
    *,
    outcome: MemoryWriteActivityOutcome,
    reason_code: str,
    canonical: CanonicalMemoryV1 | None,
    fingerprint: str | None,
) -> MemoryCommitPolicyResult:
    return MemoryCommitPolicyResult(
        decision=MemoryGovernorDecision.REJECT,
        outcome=outcome,
        reason_code=reason_code,
        target=None,
        canonical=canonical,
        proposal_fingerprint=fingerprint,
    )


class MemoryCommitPolicy:
    def evaluate(
        self,
        *,
        proposal: MemoryGovernorProposal,
        governor_result: MemoryGovernorResult,
        user_text: str,
        user_message_id: str,
        current_heads: Sequence[MemoryCommitTarget],
        tombstone_match: str | None,
    ) -> MemoryCommitPolicyResult:
        if governor_result.decision is MemoryGovernorDecision.REJECT:
            return _rejected_result(
                outcome=MemoryWriteActivityOutcome.REJECTED_GOVERNOR_POLICY,
                reason_code=governor_result.reason_code,
                canonical=None,
                fingerprint=None,
            )

        canonical = canonicalize_memory_v1(
            memory_type=proposal.memory_type,
            subject=proposal.subject,
            content=proposal.content,
        )
        fingerprint = proposal_fingerprint_v1(proposal=proposal)
        if tombstone_match in {
            "exact_canonical_key",
            "subject_key",
            "normalized_content",
        }:
            return _rejected_result(
                outcome=MemoryWriteActivityOutcome.SKIPPED_TOMBSTONE,
                reason_code="skipped_tombstone",
                canonical=canonical,
                fingerprint=fingerprint,
            )
        if not verify_explicit_user_assertion(
            proposal=proposal,
            user_text=user_text,
            user_message_id=user_message_id,
        ):
            return _rejected_result(
                outcome=MemoryWriteActivityOutcome.UNVERIFIED_USER_CLAIM,
                reason_code="unverified_user_claim",
                canonical=canonical,
                fingerprint=fingerprint,
            )

        exact = select_unique_exact_target(
            eligible_records=current_heads,
            canonical_key_hash=canonical.canonical_key_hash,
            memory_type=proposal.memory_type,
            normalized_content=canonical.normalized_content,
        )
        if exact.ambiguous:
            return _rejected_result(
                outcome=MemoryWriteActivityOutcome.AMBIGUOUS_EXACT_TARGET,
                reason_code="ambiguous_exact_target",
                canonical=canonical,
                fingerprint=fingerprint,
            )
        if exact.target is not None:
            if exact.target.open_conflict:
                return _rejected_result(
                    outcome=MemoryWriteActivityOutcome.BLOCKED_OPEN_CONFLICT,
                    reason_code="blocked_open_conflict",
                    canonical=canonical,
                    fingerprint=fingerprint,
                )
            return MemoryCommitPolicyResult(
                decision=MemoryGovernorDecision.SUPPORT,
                outcome=MemoryWriteActivityOutcome.COMMITTED_SUPPORT,
                reason_code="support",
                target=exact.target,
                canonical=canonical,
                proposal_fingerprint=fingerprint,
            )

        conflict = select_unique_conflict_target(
            proposal=proposal,
            eligible_records=current_heads,
        )
        if conflict.ambiguous:
            return _rejected_result(
                outcome=MemoryWriteActivityOutcome.AMBIGUOUS_CONFLICT_TARGET,
                reason_code="ambiguous_conflict_target",
                canonical=canonical,
                fingerprint=fingerprint,
            )
        if conflict.target is not None:
            if conflict.target.open_conflict:
                return _rejected_result(
                    outcome=MemoryWriteActivityOutcome.BLOCKED_OPEN_CONFLICT,
                    reason_code="blocked_open_conflict",
                    canonical=canonical,
                    fingerprint=fingerprint,
                )
            assertion = _explicit_user_assertion(user_text)
            decision = (
                MemoryGovernorDecision.SUPERSEDE
                if assertion is not None and assertion.explicit_correction
                else MemoryGovernorDecision.CONFLICT
            )
            outcome = (
                MemoryWriteActivityOutcome.COMMITTED_SUPERSEDE
                if decision is MemoryGovernorDecision.SUPERSEDE
                else MemoryWriteActivityOutcome.CONFLICT_RECORDED
            )
            return MemoryCommitPolicyResult(
                decision=decision,
                outcome=outcome,
                reason_code=decision.value,
                target=conflict.target,
                canonical=canonical,
                proposal_fingerprint=fingerprint,
            )

        return MemoryCommitPolicyResult(
            decision=MemoryGovernorDecision.CREATE,
            outcome=MemoryWriteActivityOutcome.COMMITTED_CREATE,
            reason_code="create",
            target=None,
            canonical=canonical,
            proposal_fingerprint=fingerprint,
        )
