from dataclasses import dataclass
from http import HTTPStatus


@dataclass(frozen=True)
class ErrorResponse:
    code: str
    message: str
    status_code: int


class AppError(Exception):
    code = "app_error"
    message = "请求处理失败，请稍后重试。"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.public_message = message or self.message

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            code=self.code,
            message=self.public_message,
            status_code=int(self.status_code),
        )


class NotFoundError(AppError):
    code = "not_found"
    message = "请求的资源不存在。"
    status_code = HTTPStatus.NOT_FOUND


class ValidationAppError(AppError):
    code = "invalid_request"
    message = "请求内容无效。"
    status_code = HTTPStatus.BAD_REQUEST


class ProviderError(AppError):
    code = "provider_error"
    message = "模型服务暂时不可用，请稍后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class ProviderInvalidRequestError(ProviderError):
    code = "provider_invalid_request"
    message = "模型请求参数无效，请检查配置后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class ProviderAuthenticationError(ProviderError):
    code = "provider_authentication_failed"
    message = "模型服务认证失败，请检查本地 API Key 配置。"
    status_code = HTTPStatus.BAD_GATEWAY


class ProviderInsufficientBalanceError(ProviderError):
    code = "provider_insufficient_balance"
    message = "模型服务账户余额不足，请检查供应商账户。"
    status_code = HTTPStatus.BAD_GATEWAY


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    message = "模型服务响应超时，请稍后重试。"
    status_code = HTTPStatus.GATEWAY_TIMEOUT


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limited"
    message = "模型服务请求过于频繁，请稍后重试。"
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    message = "模型服务暂时不可用，请稍后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class ProviderInvalidResponseError(ProviderError):
    code = "provider_invalid_response"
    message = "模型服务返回了无法处理的响应。"
    status_code = HTTPStatus.BAD_GATEWAY


class ASRError(AppError):
    code = "asr_unavailable"
    message = "语音转写服务暂时不可用，请稍后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class ASRInvalidRequestError(ASRError):
    code = "asr_invalid_request"
    message = "语音转写请求无效，请重新录制或手动输入。"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class ASRFileMissingError(ASRError):
    code = "asr_file_missing"
    message = "未找到录音文件，请重新录制后上传。"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class ASRContentTypeMissingError(ASRError):
    code = "asr_unsupported_media_type"
    message = "未提供录音文件的媒体类型，请使用支持的浏览器录制。"
    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class ASRUnsupportedMediaTypeError(ASRError):
    code = "asr_unsupported_media_type"
    message = "暂不支持该音频格式，请使用支持的浏览器录音格式。"
    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class ASRFileTooLargeError(ASRError):
    code = "asr_file_too_large"
    message = "录音文件过大，请缩短录音后重试。"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class ASRInvalidAudioError(ASRError):
    code = "asr_invalid_audio"
    message = "录音文件格式无效或与声明类型不匹配。"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class ASRTimeoutError(ASRError):
    code = "asr_timeout"
    message = "语音转写响应超时，请稍后重试。"
    status_code = HTTPStatus.GATEWAY_TIMEOUT


class ASRUnavailableError(ASRError):
    code = "asr_unavailable"
    message = "语音转写服务暂时不可用，请稍后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class ASRInvalidResponseError(ASRError):
    code = "asr_invalid_response"
    message = "语音转写服务返回了无法处理的结果。"
    status_code = HTTPStatus.BAD_GATEWAY


class TTSError(AppError):
    code = "tts_unavailable"
    message = "语音合成服务暂时不可用，请稍后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class TTSInvalidRequestError(TTSError):
    code = "tts_invalid_request"
    message = "语音合成请求无效，请检查文本、声音或语速设置。"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class TTSUnavailableError(TTSError):
    code = "tts_unavailable"
    message = "语音合成服务暂时不可用，请稍后重试。"
    status_code = HTTPStatus.BAD_GATEWAY


class TTSInvalidResponseError(TTSError):
    code = "tts_invalid_response"
    message = "语音合成服务返回了无法播放的音频。"
    status_code = HTTPStatus.BAD_GATEWAY


class TTSTimeoutError(TTSError):
    code = "tts_timeout"
    message = "语音合成响应超时，请稍后重试。"
    status_code = HTTPStatus.GATEWAY_TIMEOUT


def sanitize_error_text(text: str, secret_values: list[str | None]) -> str:
    sanitized = text
    for secret in secret_values:
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized
