from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from config import settings
from errors import AppError

logger = logging.getLogger(__name__)

STAGE = "upload"


@dataclass(frozen=True)
class ProbeResult:
    container: str
    codec: str
    duration_s: float
    size_bytes: int


def _raise_parse_failed() -> NoReturn:
    raise AppError(
        422,
        "AUDIO_PARSE_FAILED",
        "音频文件损坏或格式异常，请重新录音",
        STAGE,
    )


def _parse_positive_float(value: object) -> float | None:
    if value in (None, "", "N/A", "n/a"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _run_ffprobe(args: list[str]) -> subprocess.CompletedProcess[str]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise AppError(
            502,
            "AUDIO_PROBE_UNAVAILABLE",
            "音频校验工具不可用，请安装 ffmpeg 后重试",
            STAGE,
        )
    try:
        return subprocess.run(
            [ffprobe, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.ffprobe_timeout_s,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out")
        _raise_parse_failed()


def _probe_metadata(path: Path) -> dict:
    completed = _run_ffprobe(
        [
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    if completed.returncode != 0:
        logger.warning("ffprobe metadata failed: %s", completed.stderr.strip())
        _raise_parse_failed()
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        _raise_parse_failed()
    if not isinstance(payload, dict):
        _raise_parse_failed()
    return payload


def _duration_from_packets(path: Path) -> float | None:
    completed = _run_ffprobe(
        [
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    if completed.returncode != 0:
        logger.warning("ffprobe packet scan failed: %s", completed.stderr.strip())
        return None
    duration = None
    for line in completed.stdout.splitlines():
        parsed = _parse_positive_float(line.strip())
        if parsed is not None:
            duration = parsed
    return duration


def probe_webm_opus(path: Path, size_bytes: int) -> ProbeResult:
    payload = _probe_metadata(path)
    format_info = payload.get("format") or {}
    container = str(format_info.get("format_name") or "").lower()
    if "webm" not in container:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 格式，请更换浏览器后重试",
            STAGE,
        )

    audio_stream = None
    for stream in payload.get("streams") or []:
        if stream.get("codec_type") == "audio":
            audio_stream = stream
            break
    if not audio_stream:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 格式，请更换浏览器后重试",
            STAGE,
        )

    codec = str(audio_stream.get("codec_name") or "").lower()
    if codec != "opus":
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 格式，请更换浏览器后重试",
            STAGE,
        )

    duration_s = _parse_positive_float(format_info.get("duration"))
    if duration_s is None:
        duration_s = _parse_positive_float(audio_stream.get("duration"))
    if duration_s is None:
        duration_s = _duration_from_packets(path)
    if duration_s is None:
        _raise_parse_failed()

    if duration_s < settings.min_audio_duration_s:
        raise AppError(
            422,
            "AUDIO_TOO_SHORT",
            "录音过短，请说完整句话后松开按钮",
            STAGE,
        )
    if duration_s > settings.max_audio_duration_s:
        raise AppError(
            422,
            "AUDIO_TOO_LONG",
            "录音超过 60 秒，请重新录制",
            STAGE,
        )

    return ProbeResult(
        container=container,
        codec=codec,
        duration_s=duration_s,
        size_bytes=size_bytes,
    )
