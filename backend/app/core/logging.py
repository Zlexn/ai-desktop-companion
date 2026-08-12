import logging

from app.core.config import Settings
from app.core.errors import sanitize_error_text


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str | None]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True

        def redact(value: object) -> object:
            if not isinstance(value, str):
                return value
            return sanitize_error_text(value, self._secrets)

        record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact(value) for key, value in record.args.items()
                }
            else:
                record.args = tuple(redact(value) for value in record.args)
        return True


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    redaction_filter = SecretRedactionFilter(
        [settings.anthropic_api_key, settings.deepseek_api_key]
    )
    for logger_name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        for existing_filter in tuple(logger.filters):
            if isinstance(existing_filter, SecretRedactionFilter):
                logger.removeFilter(existing_filter)
        logger.addFilter(redaction_filter)
