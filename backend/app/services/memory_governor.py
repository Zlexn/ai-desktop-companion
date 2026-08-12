from datetime import date
import math
import re

from app.domain.models import (
    MemoryGovernorDecision,
    MemoryGovernorProposal,
    MemoryGovernorResult,
    MemoryType,
)
from app.services.memory_commit_policy import (
    canonicalize_memory_v1,
    normalize_memory_text_v1,
)


MEMORY_GOVERNOR_VERSION = "memory-governor-rules-v1"

_EXPLICIT_NO_MEMORY_PATTERNS = (
    re.compile(
        r"(?:不要|别|请勿|无需|不用|不希望|不想|不愿).{0,12}"
        r"(?:记住|记下|记录|保存|存储|留存)"
    ),
    re.compile(
        r"\b(?:do not|don't|dont|never)\s+(?:(?:want|wish)\s+(?:you\s+)?to\s+)?"
        r"(?:remember|record|save|store)\b",
        re.IGNORECASE,
    ),
)
_DELETION_INTENT_PATTERNS = (
    re.compile(
        r"(?:请|帮我|请帮我|麻烦)?\s*(?:忘掉|删除|清除|移除|抹掉)"
        r".{0,24}(?:记忆|记录|偏好|这件事|这个|我的)"
    ),
    re.compile(
        r"(?:请|帮我|请帮我|麻烦)?\s*(?:记忆|记录|偏好|这件事|这个|我的)"
        r".{0,24}(?:忘掉|删除|清除|移除|抹掉)"
    ),
)
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_API_KEY_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z0-9_-])sk-(?:ant-)?[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:api[ _-]?key|access[ _-]?token|secret[ _-]?key)\s*[:=：]\s*"
        r"[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    ),
)
_VERIFICATION_CODE_PATTERN = re.compile(
    r"(?:验证码|校验码|动态码|一次性密码|verification\s*code|one[ -]?time\s*(?:code|password)|otp)"
    r"\s*(?:是|为|[:=：])?\s*\d{4,8}(?!\d)",
    re.IGNORECASE,
)
_PASSWORD_PATTERN = re.compile(
    r"(?:密码|口令|password|passcode)\s*(?:是|为|[:=：])\s*\S+",
    re.IGNORECASE,
)
_PAYMENT_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_PRC_ID_CANDIDATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d{17}[0-9Xx]|\d{15})(?![0-9A-Za-z])"
)


def _normalize(value: str) -> str:
    return normalize_memory_text_v1(value)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)


def _passes_luhn(number: str) -> bool:
    total = 0
    parity = len(number) % 2
    for index, character in enumerate(number):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _contains_payment_credential(text: str) -> bool:
    for match in _PAYMENT_CANDIDATE_PATTERN.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and _passes_luhn(digits):
            return True
    return False


def _is_valid_calendar_date(value: str) -> bool:
    try:
        date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except ValueError:
        return False
    return True


def _is_valid_prc_identity_number(candidate: str) -> bool:
    if len(candidate) == 15:
        return _is_valid_calendar_date(f"19{candidate[6:12]}")

    if not _is_valid_calendar_date(candidate[6:14]):
        return False
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checks = "10X98765432"
    checksum_index = sum(
        int(value) * weight for value, weight in zip(candidate[:17], weights)
    ) % 11
    return candidate[-1].upper() == checks[checksum_index]


def _contains_identity_credential(text: str) -> bool:
    return any(
        _is_valid_prc_identity_number(match.group())
        for match in _PRC_ID_CANDIDATE_PATTERN.finditer(text)
    )


def _credential_reason(*texts: str) -> str | None:
    normalized_texts = tuple(_normalize(text) for text in texts)
    checks = (
        ("sensitive_private_key", lambda text: _PRIVATE_KEY_PATTERN.search(text) is not None),
        ("sensitive_api_key", lambda text: _matches_any(text, _API_KEY_PATTERNS)),
        (
            "sensitive_verification_code",
            lambda text: _VERIFICATION_CODE_PATTERN.search(text) is not None,
        ),
        ("sensitive_password", lambda text: _PASSWORD_PATTERN.search(text) is not None),
        ("sensitive_payment_credential", _contains_payment_credential),
        ("sensitive_identity_credential", _contains_identity_credential),
    )
    for reason_code, check in checks:
        if any(check(text) for text in normalized_texts):
            return reason_code
    return None


def _is_deletion_directive(clause: str) -> bool:
    clause = clause.strip()
    if not clause:
        return False
    if re.match(r"^(?:do not|don't|dont)\s+forget\b", clause):
        return False
    if _matches_any(clause, _DELETION_INTENT_PATTERNS):
        return True
    return (
        re.match(
            r"^(?:(?:please|kindly)\s+|"
            r"(?:can|could|would|will)\s+you\s+|"
            r"i\s+(?:want|need|would like)\s+you\s+to\s+)?"
            r"(?:forget|delete|remove|erase|clear)\b"
            r".{0,40}\b(?:my|saved|memory|memories|preference|record)\b",
            clause,
        )
        is not None
    )


def memory_payload_policy_reason(*texts: str) -> str | None:
    return _credential_reason(*texts)


def _turn_policy_reason(user_text: str) -> str | None:
    normalized_user_text = _normalize(user_text)
    if _matches_any(normalized_user_text, _EXPLICIT_NO_MEMORY_PATTERNS):
        return "explicit_no_memory"
    clauses = re.split(r"[,，;；。!?！？]+|\bbut\b", normalized_user_text)
    if any(_is_deletion_directive(clause) for clause in clauses):
        return "deletion_intent"
    return None


def _validated_confidence(confidence: object) -> float | None:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    try:
        value = float(confidence)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return None
    return value


def _safe_confidence(confidence: object) -> float:
    validated = _validated_confidence(confidence)
    return 0.0 if validated is None else validated


def _rejection(
    reason_code: str,
    *,
    confidence: object = 0.0,
    redaction_count: int = 0,
) -> MemoryGovernorResult:
    return MemoryGovernorResult(
        decision=MemoryGovernorDecision.REJECT,
        reason_code=reason_code,
        canonical_key=None,
        confidence=_safe_confidence(confidence),
        redaction_count=redaction_count,
    )


class MemoryGovernor:
    def __init__(
        self,
        *,
        max_proposals: int,
        max_proposal_characters: int,
        max_total_characters: int,
    ) -> None:
        for name, value in (
            ("max_proposals", max_proposals),
            ("max_proposal_characters", max_proposal_characters),
            ("max_total_characters", max_total_characters),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if max_total_characters < max_proposal_characters:
            raise ValueError(
                "max_total_characters must be at least max_proposal_characters"
            )
        self._max_proposals = max_proposals
        self._max_proposal_characters = max_proposal_characters
        self._max_total_characters = max_total_characters

    def preflight_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
    ) -> MemoryGovernorResult | None:
        policy_reason = _turn_policy_reason(user_text)
        if policy_reason is not None:
            return _rejection(policy_reason)

        credential_reason = _credential_reason(user_text, assistant_text)
        if credential_reason is not None:
            return _rejection(credential_reason, redaction_count=1)
        return None

    def evaluate_many(
        self,
        *,
        proposals: list[MemoryGovernorProposal],
        user_text: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> list[MemoryGovernorResult]:
        results: list[MemoryGovernorResult] = []
        accepted_characters = 0
        accepted_proposals = 0
        seen_canonical_hashes: set[str] = set()

        policy_reason = _turn_policy_reason(user_text)
        for candidate in proposals:
            result = self._evaluate_proposal(
                proposal=candidate,
                policy_reason=policy_reason,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            )
            if result.decision is not MemoryGovernorDecision.CREATE:
                results.append(result)
                continue

            assert result.canonical_key is not None
            if result.canonical_key in seen_canonical_hashes:
                results.append(
                    _rejection(
                        "duplicate_canonical_hash",
                        confidence=result.confidence,
                    )
                )
                continue
            seen_canonical_hashes.add(result.canonical_key)

            if accepted_proposals >= self._max_proposals:
                results.append(
                    _rejection(
                        "proposal_budget_exceeded",
                        confidence=result.confidence,
                    )
                )
                continue

            content_characters = len(candidate.content)
            if accepted_characters + content_characters > self._max_total_characters:
                results.append(
                    _rejection(
                        "turn_character_budget_exceeded",
                        confidence=result.confidence,
                    )
                )
                continue

            accepted_proposals += 1
            accepted_characters += content_characters
            results.append(result)

        return results

    def evaluate(
        self,
        *,
        proposal: MemoryGovernorProposal,
        user_text: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> MemoryGovernorResult:
        return self._evaluate_proposal(
            proposal=proposal,
            policy_reason=_turn_policy_reason(user_text),
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )

    def _evaluate_proposal(
        self,
        *,
        proposal: MemoryGovernorProposal,
        policy_reason: str | None,
        user_message_id: str,
        assistant_message_id: str,
    ) -> MemoryGovernorResult:
        if policy_reason is not None:
            return _rejection(policy_reason, confidence=proposal.confidence)

        if not isinstance(proposal.content, str):
            return _rejection("invalid_content", confidence=proposal.confidence)
        normalized_content = _normalize(proposal.content)
        if not normalized_content:
            return _rejection("invalid_content", confidence=proposal.confidence)
        if len(proposal.content) > self._max_proposal_characters:
            return _rejection("proposal_too_long", confidence=proposal.confidence)

        confidence = _validated_confidence(proposal.confidence)
        if confidence is None:
            return _rejection("invalid_confidence")

        if type(proposal.memory_type) is not MemoryType:
            return _rejection("invalid_memory_type", confidence=confidence)
        if not isinstance(proposal.subject, str):
            return _rejection("invalid_subject", confidence=confidence)
        normalized_subject = _normalize(proposal.subject)
        if not normalized_subject:
            return _rejection("invalid_subject", confidence=confidence)
        if len(proposal.subject) > 120:
            return _rejection("subject_too_long", confidence=confidence)

        credential_reason = _credential_reason(proposal.subject, proposal.content)
        if credential_reason is not None:
            return _rejection(
                credential_reason,
                confidence=confidence,
                redaction_count=1,
            )

        source_ids = proposal.source_message_ids
        allowed_source_ids = {user_message_id, assistant_message_id}
        if (
            not isinstance(source_ids, tuple)
            or not source_ids
            or any(not isinstance(source_id, str) for source_id in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or user_message_id not in source_ids
            or not set(source_ids) <= allowed_source_ids
        ):
            return _rejection("invalid_source", confidence=confidence)

        canonical_key = canonicalize_memory_v1(
            memory_type=proposal.memory_type,
            subject=proposal.subject,
            content=proposal.content,
        ).canonical_key_hash
        return MemoryGovernorResult(
            decision=MemoryGovernorDecision.CREATE,
            reason_code="eligible_shadow_create",
            canonical_key=canonical_key,
            confidence=confidence,
            redaction_count=0,
        )
