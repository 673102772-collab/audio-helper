from __future__ import annotations

import logging

import httpx
from dotenv import dotenv_values

from config import ENV_PATH, settings
from services.storage import save_tts_audio

logger = logging.getLogger(__name__)
STAGE = "tts"
TTS_WARNING = "语音合成服务暂时不可用，请阅读文字结果"
DOWNLOAD_WARNING = "语音文件下载失败，请阅读文字结果"


class TtsDegraded(Exception):
    def __init__(self, warning: str) -> None:
        self.warning = warning
        super().__init__(warning)


def _api_key() -> str:
    memory_key = (settings.bailian_api_key or "").strip()
    if memory_key:
        return memory_key
    return (dotenv_values(ENV_PATH).get("BAILIAN_API_KEY") or "").strip()


def detect_audio_format(data: bytes, content_type: str | None = None) -> tuple[str, str] | None:
    del content_type
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa"}:
        return "mp3", "audio/mpeg"
    if data.startswith(b"OggS"):
        return "ogg", "audio/ogg"
    return None


def _extract_audio_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    audio = output.get("audio")
    if not isinstance(audio, dict):
        return None
    url = audio.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None


async def synthesize_and_store(reply_text: str, search_id: str) -> str:
    api_key = _api_key()
    if not api_key:
        logger.warning("stage=tts reason=missing_api_key")
        raise TtsDegraded(TTS_WARNING)

    payload = {
        "model": settings.bailian_tts_model,
        "input": {
            "text": reply_text,
            "voice": settings.bailian_tts_voice,
            "language_type": settings.bailian_tts_language_type,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.bailian_tts_timeout_s) as client:
            response = await client.post(
                settings.bailian_tts_url,
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException:
        logger.warning("stage=tts reason=timeout")
        raise TtsDegraded(TTS_WARNING) from None
    except httpx.HTTPError:
        logger.warning("stage=tts reason=http_error")
        raise TtsDegraded(TTS_WARNING) from None

    if response.status_code >= 400:
        logger.warning("stage=tts reason=vendor_status status=%s", response.status_code)
        raise TtsDegraded(TTS_WARNING)

    try:
        body = response.json()
    except ValueError:
        raise TtsDegraded(TTS_WARNING) from None
    if not isinstance(body, dict):
        raise TtsDegraded(TTS_WARNING)
    vendor_code = body.get("code")
    if vendor_code not in (None, "", "Success"):
        logger.warning("stage=tts reason=vendor_code")
        raise TtsDegraded(TTS_WARNING)
    audio_url = _extract_audio_url(body)
    if not audio_url:
        logger.warning("stage=tts reason=missing_audio_url")
        raise TtsDegraded(TTS_WARNING)

    try:
        async with httpx.AsyncClient(
            timeout=settings.tts_download_timeout_s,
            follow_redirects=True,
        ) as client:
            download = await client.get(audio_url)
    except httpx.TimeoutException:
        logger.warning("stage=tts reason=download_timeout")
        raise TtsDegraded(DOWNLOAD_WARNING) from None
    except httpx.HTTPError:
        logger.warning("stage=tts reason=download_http_error")
        raise TtsDegraded(DOWNLOAD_WARNING) from None

    if download.status_code >= 400 or not download.content:
        logger.warning("stage=tts reason=download_status status=%s", download.status_code)
        raise TtsDegraded(DOWNLOAD_WARNING)

    detected = detect_audio_format(download.content)
    if detected is None:
        logger.warning("stage=tts reason=unknown_audio_format")
        raise TtsDegraded(DOWNLOAD_WARNING)
    extension, content_type = detected
    audio_id = save_tts_audio(
        download.content,
        content_type=content_type,
        extension=extension,
        search_id=search_id,
    )
    logger.info("stage=tts saved audio_id=%s content_type=%s size_bytes=%s", audio_id, content_type, len(download.content))
    return audio_id
