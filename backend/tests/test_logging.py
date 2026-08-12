import logging

from app.core.config import Settings
from app.core.logging import SecretRedactionFilter, configure_logging


def test_secret_redaction_preserves_uvicorn_access_argument_shape() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", "/docs?token=secret-token", "1.1", 200),
        exc_info=None,
    )

    assert SecretRedactionFilter(["secret-token"]).filter(record)

    assert record.msg == '%s - "%s %s HTTP/%s" %d'
    assert record.args == (
        "127.0.0.1:12345",
        "GET",
        "/docs?token=***",
        "1.1",
        200,
    )


def test_secret_redaction_handles_template_and_arguments() -> None:
    record = logging.LogRecord(
        name="app.provider",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="remote failure for token=secret-token: %s",
        args=("request secret-token failed",),
        exc_info=None,
    )

    assert SecretRedactionFilter(["secret-token"]).filter(record)

    assert record.msg == "remote failure for token=***: %s"
    assert record.args == ("request *** failed",)
    assert record.getMessage() == "remote failure for token=***: request *** failed"


def test_configure_logging_replaces_existing_redaction_filter() -> None:
    logger_names = ("app", "uvicorn", "uvicorn.error", "uvicorn.access")
    original_filters = {
        name: list(logging.getLogger(name).filters) for name in logger_names
    }
    try:
        configure_logging(Settings(anthropic_api_key="first-secret"))
        configure_logging(Settings(anthropic_api_key="second-secret"))

        for name in logger_names:
            filters = logging.getLogger(name).filters
            assert sum(
                isinstance(log_filter, SecretRedactionFilter)
                for log_filter in filters
            ) == 1
    finally:
        for name, filters in original_filters.items():
            logger = logging.getLogger(name)
            logger.filters[:] = filters
