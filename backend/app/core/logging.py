import logging

from app.core.config import Settings


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str | None]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self._secrets:
            message = message.replace(secret, "***")
        record.msg = message
        record.args = ()
        return True


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    redaction_filter = SecretRedactionFilter([settings.anthropic_api_key, settings.deepseek_api_key])
    for logger_name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).addFilter(redaction_filter)
