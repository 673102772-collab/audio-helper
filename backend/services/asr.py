from __future__ import annotations

import base64
import logging
from typing import Any, NoReturn

import httpx
from dotenv import dotenv_values

from config import ENV_PATH, settings
from errors import AppError

logger = logging.getLogger(__name__)
STAGE = "asr"
ASR_SERVICE_MESSAGE = "语音识别服务异常（阶段：asr），请稍后重试"
ASR_MISSING_KEY_MESSAGE = "未配置 BAILIAN_API_KEY，无法调用语音识别服务"


def _service_error() -> NoReturn:
    raise AppError(502, "ASR_SERVICE_ERROR", ASR_SERVICE_MESSAGE, STAGE)


def _api_key() -> str:
    memory_key = (settings.bailian_api_key or "").strip()
    if memory_key:
        return memory_key
    return (dotenv_values(ENV_PATH).get("BAILIAN_API_KEY") or "").strip()


def _extract_text(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        output = payload
    choices = output.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text") is not None:
                parts.append(str(item["text"]))
        return "".join(parts).strip()
    return None


async def transcribe(audio_bytes: bytes) -> str:
    api_key = _api_key()
    if not api_key:
        logger.warning("stage=asr reason=missing_api_key")
        raise AppError(502, "ASR_SERVICE_ERROR", ASR_MISSING_KEY_MESSAGE, STAGE)

    encoded = base64.b64encode(audio_bytes).decode("ascii")
    if len(encoded) > settings.max_asr_base64_bytes:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "录音编码后体积过大，无法识别",
            STAGE,
        )

    payload = {
        "model": settings.bailian_asr_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"audio": f"data:audio/webm;base64,{encoded}"},
                    ],
                }
            ]
        },
        "parameters": {
            "asr_options": {
                "language": settings.bailian_asr_language,
                "enable_itn": settings.bailian_asr_enable_itn,
            }
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.bailian_asr_timeout_s) as client:
            response = await client.post(
                settings.bailian_asr_url,
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException:
        logger.warning("stage=asr reason=timeout")
        raise AppError(504, "ASR_TIMEOUT", "语音识别服务超时，请稍后重试", STAGE) from None
    except httpx.HTTPError:
        logger.warning("stage=asr reason=http_error")
        _service_error()

    if response.status_code >= 400:
        logger.warning("stage=asr reason=vendor_status status=%s", response.status_code)
        _service_error()

    try:
        body = response.json()
    except ValueError:
        logger.warning("stage=asr reason=invalid_json")
        _service_error()

    if not isinstance(body, dict):
        logger.warning("stage=asr reason=invalid_payload")
        _service_error()

    vendor_code = body.get("code")
    if vendor_code not in (None, "", "Success"):
        logger.warning("stage=asr reason=vendor_code")
        _service_error()

    text = _extract_text(body)
    if text is None:
        logger.warning("stage=asr reason=invalid_output")
        _service_error()
    if text == "":
        raise AppError(
            422,
            "ASR_EMPTY_RESULT",
            "未能识别到有效内容，请在安静环境重新录音",
            STAGE,
        )
    return text
