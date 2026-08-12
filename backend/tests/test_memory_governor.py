from dataclasses import asdict
import math

import pytest

from app.domain.models import (
    MemoryGovernorDecision,
    MemoryGovernorProposal,
    MemoryType,
)
from app.services.memory_governor import (
    MEMORY_GOVERNOR_VERSION,
    MemoryGovernor,
)


@pytest.fixture
def governor() -> MemoryGovernor:
    return MemoryGovernor(
        max_proposals=3,
        max_proposal_characters=200,
        max_total_characters=600,
    )


def proposal(
    *,
    content: object = "我喜欢黑咖啡",
    memory_type: object = MemoryType.PREFERENCE,
    subject: object = "饮品偏好",
    confidence: object = 0.9,
    source_message_ids: object = ("user-1",),
    canonical_key_hint: object = None,
) -> MemoryGovernorProposal:
    return MemoryGovernorProposal(
        memory_type=memory_type,  # type: ignore[arg-type]
        subject=subject,  # type: ignore[arg-type]
        content=content,  # type: ignore[arg-type]
        canonical_key_hint=canonical_key_hint,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        source_message_ids=source_message_ids,  # type: ignore[arg-type]
    )


def evaluate(
    governor: MemoryGovernor,
    candidate: MemoryGovernorProposal | None = None,
    *,
    user_text: str = "我喜欢黑咖啡",
):
    return governor.evaluate(
        proposal=candidate or proposal(),
        user_text=user_text,
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )


def assert_rejected(result, reason_code: str, *, redaction_count: int = 0) -> None:
    assert result.decision is MemoryGovernorDecision.REJECT
    assert result.reason_code == reason_code
    assert result.canonical_key is None
    assert result.redaction_count == redaction_count


def test_governor_version_is_frozen():
    assert MEMORY_GOVERNOR_VERSION == "memory-governor-rules-v1"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_proposals", True),
        ("max_proposals", 1.0),
        ("max_proposals", math.nan),
        ("max_proposal_characters", False),
        ("max_proposal_characters", 200.0),
        ("max_proposal_characters", math.inf),
        ("max_total_characters", True),
        ("max_total_characters", 600.0),
        ("max_total_characters", -math.inf),
    ],
)
def test_governor_requires_exact_positive_integer_budgets(name, value):
    budgets = {
        "max_proposals": 3,
        "max_proposal_characters": 200,
        "max_total_characters": 600,
    }
    budgets[name] = value

    with pytest.raises(ValueError):
        MemoryGovernor(**budgets)


def test_governor_classifies_eligible_proposal_as_shadow_create(governor):
    result = evaluate(governor)

    assert result.decision is MemoryGovernorDecision.CREATE
    assert result.reason_code == "eligible_shadow_create"
    assert result.canonical_key is not None
    assert len(result.canonical_key) == 64
    assert result.confidence == 0.9
    assert result.redaction_count == 0


@pytest.mark.parametrize(
    ("user_text", "reason_code"),
    [
        ("不要记住，我喜欢黑咖啡", "explicit_no_memory"),
        ("请别记下这个偏好", "explicit_no_memory"),
        ("do not remember that I like coffee", "explicit_no_memory"),
        ("我不希望你记住我的咖啡偏好", "explicit_no_memory"),
        ("I do not want you to remember my coffee preference", "explicit_no_memory"),
        ("忘掉我的咖啡偏好", "deletion_intent"),
        ("请删除关于咖啡的记忆", "deletion_intent"),
        ("forget my coffee preference", "deletion_intent"),
    ],
)
def test_governor_rejects_explicit_turn_policies_for_every_proposal(
    governor, user_text, reason_code
):
    result = evaluate(governor, user_text=user_text)

    assert_rejected(result, reason_code)


@pytest.mark.parametrize(
    ("text", "reason_code"),
    [
        ("-----BEGIN PRIVATE KEY-----\nfixture", "sensitive_private_key"),
        ("API key: sk-ant-test-1234567890", "sensitive_api_key"),
        ("验证码 493821", "sensitive_verification_code"),
        ("我的密码是 swordfish", "sensitive_password"),
        ("银行卡号 4111 1111 1111 1111", "sensitive_payment_credential"),
        ("身份证号 11010519491231002X", "sensitive_identity_credential"),
        ("验证码493821有效", "sensitive_verification_code"),
        ("API key: sk-ant-test-1234567890有效", "sensitive_api_key"),
    ],
)
@pytest.mark.parametrize("text_field", ["user_text", "assistant_text"])
def test_preflight_turn_rejects_credentials_in_user_or_assistant_text(
    governor, text, reason_code, text_field
):
    turn = {"user_text": "普通消息", "assistant_text": "普通回复"}
    turn[text_field] = text

    result = governor.preflight_turn(**turn)

    assert result is not None
    assert_rejected(result, reason_code, redaction_count=1)
    assert result.confidence == 0.0


def test_preflight_turn_does_not_apply_assistant_no_memory_language(governor):
    result = governor.preflight_turn(
        user_text="我喜欢黑咖啡",
        assistant_text="我不会记住你刚才的话",
    )

    assert result is None


@pytest.mark.parametrize(
    ("user_text", "reason_code"),
    [
        ("不要记住，我喜欢黑咖啡", "explicit_no_memory"),
        ("忘掉我的咖啡偏好", "deletion_intent"),
    ],
)
def test_preflight_turn_rejects_user_memory_directives(governor, user_text, reason_code):
    result = governor.preflight_turn(user_text=user_text, assistant_text="好的")

    assert result is not None
    assert_rejected(result, reason_code)


@pytest.mark.parametrize(
    "user_text",
    [
        "请不要忘记带伞",
        "别忘记带伞",
        "don't forget your umbrella",
        "do not forget the umbrella",
        "don't forget my coffee preference",
        "do not forget my saved preference",
        "我总是忘记带伞",
        "I forget my coffee preference sometimes",
        "I sometimes forget my saved coffee preference",
        "sky is clear",
    ],
)
def test_preflight_does_not_treat_negated_or_ordinary_forgetting_as_deletion(
    governor, user_text
):
    assert governor.preflight_turn(user_text=user_text, assistant_text="好的") is None


@pytest.mark.parametrize(
    "user_text",
    [
        "请不要忘记我的咖啡偏好；请删除我的茶饮偏好记录",
        "请不要忘记我的咖啡偏好，请删除我的茶饮偏好记录",
        "请不要忘记我的咖啡偏好, 删除我的茶饮偏好记录",
        "do not forget my coffee preference, delete my saved tea preference",
        "do not forget my coffee preference; please delete my saved tea preference",
        "don't forget my coffee preference, but delete my saved tea preference",
    ],
)
def test_preflight_detects_deletion_in_separate_mixed_preservation_clause(
    governor, user_text
):
    result = governor.preflight_turn(user_text=user_text, assistant_text="好的")

    assert result is not None
    assert_rejected(result, "deletion_intent")


@pytest.mark.parametrize(
    "user_text",
    [
        "请忘掉我的咖啡偏好",
        "删除关于咖啡的记忆",
        "please forget my coffee preference",
        "delete my saved coffee preference",
    ],
)
def test_preflight_rejects_positive_deletion_directives(governor, user_text):
    result = governor.preflight_turn(user_text=user_text, assistant_text="好的")

    assert result is not None
    assert_rejected(result, "deletion_intent")


def test_preflight_strips_format_characters_before_policy_and_credential_matching(
    governor,
):
    no_memory = governor.preflight_turn(
        user_text="不​要记住这个偏好",
        assistant_text="普通回复",
    )
    api_key = governor.preflight_turn(
        user_text="普通消息",
        assistant_text="API key: sk-ant-test-12345​67890",
    )
    password = governor.preflight_turn(
        user_text="我的密​码是 swordfish",
        assistant_text="普通回复",
    )

    assert no_memory is not None
    assert_rejected(no_memory, "explicit_no_memory")
    assert api_key is not None
    assert_rejected(api_key, "sensitive_api_key", redaction_count=1)
    assert password is not None
    assert_rejected(password, "sensitive_password", redaction_count=1)


def test_preflight_turn_returns_none_for_safe_turn(governor):
    assert (
        governor.preflight_turn(
            user_text="我喜欢黑咖啡",
            assistant_text="知道了",
        )
        is None
    )


@pytest.mark.parametrize(
    ("content", "reason_code"),
    [
        ("", "invalid_content"),
        (" \t\n ", "invalid_content"),
        (None, "invalid_content"),
        (123, "invalid_content"),
        ("喜" * 201, "proposal_too_long"),
    ],
)
def test_governor_rejects_invalid_or_oversized_content(governor, content, reason_code):
    result = evaluate(governor, proposal(content=content))

    assert_rejected(result, reason_code)


def test_governor_counts_original_characters_for_per_proposal_budget(governor):
    result = evaluate(governor, proposal(content=("喜" * 199) + "  "))

    assert_rejected(result, "proposal_too_long")


@pytest.mark.parametrize(
    "confidence",
    [
        -0.01,
        1.2,
        math.nan,
        math.inf,
        -math.inf,
        "0.9",
        True,
        pytest.param(10**10000, id="huge-int"),
    ],
)
def test_governor_rejects_non_finite_out_of_range_or_wrong_type_confidence(
    governor, confidence
):
    result = evaluate(governor, proposal(confidence=confidence))

    assert_rejected(result, "invalid_confidence")


@pytest.mark.parametrize(
    "source_message_ids",
    [
        ("assistant-1",),
        (),
        ("user-1", "other-1"),
        ("user-1", "user-1"),
        ["user-1"],
        ("user-1", 2),
    ],
)
def test_governor_requires_unique_tuple_sources_from_current_turn_including_user(
    governor, source_message_ids
):
    result = evaluate(governor, proposal(source_message_ids=source_message_ids))

    assert_rejected(result, "invalid_source")


def test_governor_accepts_user_and_assistant_as_joint_sources(governor):
    result = evaluate(
        governor,
        proposal(source_message_ids=("user-1", "assistant-1")),
    )

    assert result.decision is MemoryGovernorDecision.CREATE


@pytest.mark.parametrize("memory_type", ["preference", "commitment", None])
def test_governor_rejects_non_enum_or_unknown_memory_types(governor, memory_type):
    result = evaluate(governor, proposal(memory_type=memory_type))

    assert_rejected(result, "invalid_memory_type")


@pytest.mark.parametrize(
    ("subject", "reason_code"),
    [
        (None, "invalid_subject"),
        (123, "invalid_subject"),
        ("", "invalid_subject"),
        ("　 ", "invalid_subject"),
        ("主" * 121, "subject_too_long"),
    ],
)
def test_governor_rejects_invalid_empty_or_oversized_subject(
    governor, subject, reason_code
):
    result = evaluate(governor, proposal(subject=subject))

    assert_rejected(result, reason_code)


@pytest.mark.parametrize(
    ("subject", "reason_code"),
    [
        ("我的密码是 swordfish", "sensitive_password"),
        ("API key: sk-ant-test-1234567890", "sensitive_api_key"),
        ("验证码 493821", "sensitive_verification_code"),
        ("-----BEGIN PRIVATE KEY-----", "sensitive_private_key"),
        ("卡号 4111111111111111", "sensitive_payment_credential"),
        ("身份证 11010519491231002X", "sensitive_identity_credential"),
    ],
)
def test_evaluate_rejects_sensitive_proposal_subject(governor, subject, reason_code):
    result = evaluate(governor, proposal(subject=subject))

    assert_rejected(result, reason_code, redaction_count=1)


@pytest.mark.parametrize(
    ("content", "reason_code"),
    [
        ("我的密码是 swordfish", "sensitive_password"),
        ("API key: sk-ant-test-1234567890", "sensitive_api_key"),
        ("验证码 493821", "sensitive_verification_code"),
        ("-----BEGIN RSA PRIVATE KEY-----", "sensitive_private_key"),
        ("卡号 4111111111111111", "sensitive_payment_credential"),
        ("身份证 11010519491231002X", "sensitive_identity_credential"),
    ],
)
def test_evaluate_rejects_sensitive_proposal_content(governor, content, reason_code):
    result = evaluate(governor, proposal(content=content))

    assert_rejected(result, reason_code, redaction_count=1)


def test_invalid_luhn_number_is_not_treated_as_payment_credential(governor):
    result = evaluate(governor, proposal(content="订单号 4111111111111112"))

    assert result.decision is MemoryGovernorDecision.CREATE


@pytest.mark.parametrize(
    "identity_number",
    [
        "11010519491231002X",
        "110105491231002",
    ],
)
def test_valid_prc_identity_numbers_are_rejected(governor, identity_number):
    result = evaluate(governor, proposal(content=f"身份证 {identity_number}"))

    assert_rejected(result, "sensitive_identity_credential", redaction_count=1)


@pytest.mark.parametrize(
    "identity_number",
    [
        "110105199902300023",
        "110105194902300020",
        "110105202302290022",
        "110105990231002",
    ],
)
def test_invalid_prc_identity_dates_are_not_credentials(governor, identity_number):
    result = evaluate(governor, proposal(content=f"编号 {identity_number}"))

    assert result.decision is MemoryGovernorDecision.CREATE


def test_invalid_prc_identity_checksum_is_not_treated_as_identity_credential(governor):
    result = evaluate(governor, proposal(content="编号 110105194912310021"))

    assert result.decision is MemoryGovernorDecision.CREATE


def test_preflight_normalizes_unicode_before_credential_detection(governor):
    result = governor.preflight_turn(
        user_text="普通消息",
        assistant_text="ＡＰＩ ｋｅｙ： ｓｋ－ａｎｔ－ｔｅｓｔ－１２３４５６７８９０",
    )

    assert result is not None
    assert_rejected(result, "sensitive_api_key", redaction_count=1)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("-----BEGIN PRIVATE KEY-----", "API key: sk-ant-test-1234567890", "sensitive_private_key"),
        ("API key: sk-ant-test-1234567890", "验证码 493821", "sensitive_api_key"),
        ("验证码 493821", "密码是 swordfish", "sensitive_verification_code"),
        ("密码是 swordfish", "卡号 4111111111111111", "sensitive_password"),
        ("卡号 4111111111111111", "身份证 11010519491231002X", "sensitive_payment_credential"),
    ],
)
def test_adjacent_credential_categories_use_frozen_precedence(
    governor, first, second, expected
):
    result = governor.preflight_turn(
        user_text=f"{second} {first}",
        assistant_text="普通回复",
    )

    assert result is not None
    assert_rejected(result, expected, redaction_count=1)


def test_credential_category_order_is_deterministic(governor):
    result = governor.preflight_turn(
        user_text="API key: sk-ant-test-1234567890 验证码 493821",
        assistant_text="-----BEGIN PRIVATE KEY-----",
    )

    assert result is not None
    assert_rejected(result, "sensitive_private_key", redaction_count=1)


def test_canonicalization_normalizes_nfkc_whitespace_and_ascii_case(governor):
    first = evaluate(
        governor,
        proposal(subject=" ＤＲＩＮＫ   Pref ", content=" I   LIKE  COFFEE "),
    )
    second = evaluate(
        governor,
        proposal(subject="drink pref", content="i like coffee"),
    )

    assert first.canonical_key == second.canonical_key
    assert first.canonical_key is not None
    assert len(first.canonical_key) == 64


def test_canonicalization_strips_unicode_format_characters(governor):
    first = evaluate(
        governor,
        proposal(subject="drink​pref", content="i like​ coffee"),
    )
    second = evaluate(
        governor,
        proposal(subject="drinkpref", content="i like coffee"),
    )

    assert first.canonical_key == second.canonical_key


def test_canonical_key_hint_is_never_authoritative(governor):
    first = evaluate(governor, proposal(canonical_key_hint="remote-one"))
    second = evaluate(governor, proposal(canonical_key_hint="remote-two"))

    assert first.canonical_key == second.canonical_key


def test_governor_deduplicates_current_response_by_canonical_hash_in_first_seen_order(
    governor,
):
    first = proposal(
        subject="DRINK PREF",
        content="I LIKE COFFEE",
        confidence=0.91,
        source_message_ids=("user-1",),
    )
    duplicate = proposal(
        subject=" ＤＲＩＮＫ   ＰＲＥＦ ",
        content=" Ｉ   ＬＩＫＥ  ＣＯＦＦＥＥ ",
        confidence=0.42,
        source_message_ids=("user-1", "assistant-1"),
    )
    distinct = proposal(
        subject="运动偏好",
        content="用户喜欢游泳",
        confidence=0.88,
    )

    results = governor.evaluate_many(
        proposals=[first, duplicate, distinct],
        user_text="我喜欢黑咖啡，也喜欢游泳",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [
        (result.decision, result.reason_code)
        for result in results
    ] == [
        (MemoryGovernorDecision.CREATE, "eligible_shadow_create"),
        (MemoryGovernorDecision.REJECT, "duplicate_canonical_hash"),
        (MemoryGovernorDecision.CREATE, "eligible_shadow_create"),
    ]
    assert results[0].canonical_key is not None
    assert results[1].canonical_key is None
    assert results[2].canonical_key is not None


def test_evaluate_many_reserves_first_canonical_hash_when_character_budget_rejects_it():
    governor = MemoryGovernor(
        max_proposals=3,
        max_proposal_characters=200,
        max_total_characters=200,
    )
    first_distinct = proposal(subject="other", content="x")
    first_canonical = proposal(subject="drink", content="coffee" + (" " * 194))
    later_duplicate = proposal(subject=" drink ", content=" COFFEE ")

    results = governor.evaluate_many(
        proposals=[first_distinct, first_canonical, later_duplicate],
        user_text="我的偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [result.reason_code for result in results] == [
        "eligible_shadow_create",
        "turn_character_budget_exceeded",
        "duplicate_canonical_hash",
    ]


def test_evaluate_many_reserves_first_canonical_hash_when_proposal_budget_rejects_it():
    governor = MemoryGovernor(
        max_proposals=1,
        max_proposal_characters=200,
        max_total_characters=200,
    )
    first_distinct = proposal(subject="other", content="x")
    first_canonical = proposal(subject="drink", content="coffee")
    later_duplicate = proposal(subject=" drink ", content=" COFFEE ")

    results = governor.evaluate_many(
        proposals=[first_distinct, first_canonical, later_duplicate],
        user_text="我的偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [result.reason_code for result in results] == [
        "eligible_shadow_create",
        "proposal_budget_exceeded",
        "duplicate_canonical_hash",
    ]


def test_evaluate_many_rejects_proposals_beyond_count_budget(governor):
    proposals = [proposal(content=f"偏好 {index}") for index in range(1, 5)]

    results = governor.evaluate_many(
        proposals=proposals,
        user_text="我的几个偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [result.reason_code for result in results] == [
        "eligible_shadow_create",
        "eligible_shadow_create",
        "eligible_shadow_create",
        "proposal_budget_exceeded",
    ]
    assert results[-1].canonical_key is None


def test_evaluate_many_accepts_exact_total_budget_and_rejects_next_nonempty_proposal():
    governor = MemoryGovernor(
        max_proposals=4,
        max_proposal_characters=200,
        max_total_characters=600,
    )
    proposals = [
        proposal(content="一" * 200),
        proposal(content="二" * 200),
        proposal(content="三" * 200),
        proposal(content="四"),
    ]

    results = governor.evaluate_many(
        proposals=proposals,
        user_text="我的偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [result.reason_code for result in results] == [
        "eligible_shadow_create",
        "eligible_shadow_create",
        "eligible_shadow_create",
        "turn_character_budget_exceeded",
    ]


def test_evaluate_many_counts_original_characters_for_exact_total_budget():
    governor = MemoryGovernor(
        max_proposals=2,
        max_proposal_characters=2,
        max_total_characters=2,
    )

    results = governor.evaluate_many(
        proposals=[proposal(content="甲 "), proposal(content="乙 ")],
        user_text="我的偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [result.reason_code for result in results] == [
        "eligible_shadow_create",
        "turn_character_budget_exceeded",
    ]


def test_rejected_proposals_do_not_consume_total_character_budget():
    governor = MemoryGovernor(
        max_proposals=3,
        max_proposal_characters=200,
        max_total_characters=200,
    )
    proposals = [
        proposal(content="API key: sk-ant-test-1234567890"),
        proposal(content="好" * 200),
    ]

    results = governor.evaluate_many(
        proposals=proposals,
        user_text="我的偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert [result.reason_code for result in results] == [
        "sensitive_api_key",
        "eligible_shadow_create",
    ]


def test_evaluate_many_preserves_one_result_per_proposal_without_truncation(governor):
    proposals = [proposal(content=f"内容 {index}") for index in range(8)]

    results = governor.evaluate_many(
        proposals=proposals,
        user_text="我的偏好",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert len(results) == len(proposals)


def test_governor_results_expose_no_raw_content(governor):
    raw_content = "我喜欢 SECRET_SENTINEL_9f40 黑咖啡"
    result = evaluate(governor, proposal(content=raw_content))
    serialized = asdict(result)

    assert set(serialized) == {
        "decision",
        "reason_code",
        "canonical_key",
        "confidence",
        "redaction_count",
    }
    assert raw_content not in repr(serialized)
    assert "SECRET_SENTINEL_9f40" not in repr(serialized)
