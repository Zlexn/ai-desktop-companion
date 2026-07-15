from app.services.session_summary_sanitizer import sanitize_summary_text


def test_sanitize_summary_text_redacts_common_credentials() -> None:
    text = (
        "Authorization: Bearer abc.def.ghi\n"
        "password=hunter2\n"
        "api_key: sk-secret-value\n"
        "普通内容保留。"
    )

    result = sanitize_summary_text(text)

    assert "abc.def.ghi" not in result
    assert "hunter2" not in result
    assert "sk-secret-value" not in result
    assert result.count("[REDACTED]") == 3
    assert "普通内容保留。" in result


def test_sanitize_summary_text_preserves_non_secret_conversation() -> None:
    assert sanitize_summary_text("用户喜欢雨天，想下周继续讨论。") == "用户喜欢雨天，想下周继续讨论。"


def test_sanitize_summary_text_redacts_prefixed_environment_names() -> None:
    text = "DB_PASSWORD=secret-one\nMY_API_KEY: secret-two\nX_ACCESS_TOKEN=secret-three"

    result = sanitize_summary_text(text)

    assert "secret-one" not in result
    assert "secret-two" not in result
    assert "secret-three" not in result
    assert "DB_PASSWORD=[REDACTED]" in result
    assert "MY_API_KEY=[REDACTED]" in result
    assert "X_ACCESS_TOKEN=[REDACTED]" in result


def test_sanitize_summary_text_preserves_chinese_prose_after_secret() -> None:
    result = sanitize_summary_text("password=hunter2。普通内容保留。")

    assert result == "password=[REDACTED]。普通内容保留。"


def test_sanitize_summary_text_redacts_quoted_assignment_values() -> None:
    text = 'PASSWORD="hunter2"\napi_key=\'ordinary-secret\'\ntoken: "abc.def"'

    result = sanitize_summary_text(text)

    assert "hunter2" not in result
    assert "ordinary-secret" not in result
    assert "abc.def" not in result
    assert result.count("[REDACTED]") == 3
