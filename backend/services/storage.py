from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from config import settings
from errors import AppError

AUDIO_ID_PATTERN = re.compile(r"^aud_[0-9a-f]{12}$")
AUDIO_NOT_FOUND_MESSAGE = "录音编号无效或已过期，请重新录音"


def generate_audio_id() -> str:
    return f"aud_{uuid4().hex[:12]}"


def audio_dir() -> Path:
    path = settings.storage_dir / "audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audio_file_path(audio_id: str) -> Path:
    return audio_dir() / f"{audio_id}.webm"


def audio_meta_path(audio_id: str) -> Path:
    return audio_dir() / f"{audio_id}.meta.json"


def save_audio(
    data: bytes,
    *,
    container: str,
    codec: str,
    duration_s: float,
) -> str:
    audio_id = generate_audio_id()
    while audio_file_path(audio_id).exists() or audio_meta_path(audio_id).exists():
        audio_id = generate_audio_id()

    file_path = audio_file_path(audio_id)
    meta_path = audio_meta_path(audio_id)
    created_at = datetime.now(timezone.utc).isoformat()
    meta = {
        "audio_id": audio_id,
        "created_at": created_at,
        "size_bytes": len(data),
        "duration_s": duration_s,
        "container": container,
        "codec": codec,
        "ttl_hours": settings.audio_ttl_hours,
    }
    try:
        file_path.write_bytes(data)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        file_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise
    return audio_id


def _audio_not_found(stage: str) -> None:
    raise AppError(404, "AUDIO_NOT_FOUND", AUDIO_NOT_FOUND_MESSAGE, stage)


def load_audio(audio_id: str, *, stage: str = "asr") -> bytes:
    if not AUDIO_ID_PATTERN.fullmatch(audio_id):
        _audio_not_found(stage)

    file_path = audio_file_path(audio_id)
    meta_path = audio_meta_path(audio_id)
    if not file_path.is_file() or not meta_path.is_file():
        _audio_not_found(stage)

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(str(meta["created_at"]))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        _audio_not_found(stage)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    expires_at = created_at + timedelta(hours=settings.audio_ttl_hours)
    if datetime.now(timezone.utc) >= expires_at:
        _audio_not_found(stage)

    try:
        return file_path.read_bytes()
    except OSError:
        _audio_not_found(stage)


SEARCH_ID_PATTERN = re.compile(r"^srch_[0-9a-f]{12}$")
TTS_ID_PATTERN = re.compile(r"^tts_[0-9a-f]{12}$")
TTS_EXTENSIONS = {"wav", "mp3", "ogg"}
SEARCH_NOT_FOUND_MESSAGE = "查询结果无效或已过期，请重新搜索"
TTS_NOT_FOUND_MESSAGE = "音频文件不存在或已过期"


def _parse_created_at(value: object) -> datetime:
    created_at = datetime.fromisoformat(str(value))
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at


def _expired(created_at: datetime, ttl_hours: int) -> bool:
    return datetime.now(timezone.utc) >= created_at + timedelta(hours=ttl_hours)


def generate_search_id() -> str:
    return f"srch_{uuid4().hex[:12]}"


def search_dir() -> Path:
    path = settings.storage_dir / "search"
    path.mkdir(parents=True, exist_ok=True)
    return path


def search_file_path(search_id: str) -> Path:
    return search_dir() / f"{search_id}.json"


def save_search(payload: dict) -> str:
    search_id = generate_search_id()
    while search_file_path(search_id).exists():
        search_id = generate_search_id()
    created_at = datetime.now(timezone.utc).isoformat()
    record = {
        "search_id": search_id,
        "created_at": created_at,
        "ttl_hours": settings.search_ttl_hours,
        **payload,
    }
    path = search_file_path(search_id)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return search_id


def _search_not_found() -> NoReturn:
    raise AppError(404, "SEARCH_NOT_FOUND", SEARCH_NOT_FOUND_MESSAGE, "finalize")


def load_search(search_id: str) -> dict:
    if not SEARCH_ID_PATTERN.fullmatch(search_id):
        _search_not_found()
    path = search_file_path(search_id)
    if not path.is_file():
        _search_not_found()
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        created_at = _parse_created_at(record["created_at"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        _search_not_found()
    ttl_hours = int(record.get("ttl_hours") or settings.search_ttl_hours)
    if _expired(created_at, ttl_hours):
        _search_not_found()
    if not isinstance(record, dict):
        _search_not_found()
    return record


def generate_tts_id() -> str:
    return f"tts_{uuid4().hex[:12]}"


def tts_dir() -> Path:
    path = settings.storage_dir / "tts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tts_meta_path(audio_id: str) -> Path:
    return tts_dir() / f"{audio_id}.meta.json"


def save_tts_audio(
    data: bytes,
    *,
    content_type: str,
    extension: str,
    search_id: str,
) -> str:
    if extension not in TTS_EXTENSIONS:
        raise ValueError("unsupported tts audio extension")
    audio_id = generate_tts_id()
    while tts_meta_path(audio_id).exists():
        audio_id = generate_tts_id()
    file_path = tts_dir() / f"{audio_id}.{extension}"
    meta_path = tts_meta_path(audio_id)
    created_at = datetime.now(timezone.utc).isoformat()
    meta = {
        "audio_id": audio_id,
        "created_at": created_at,
        "ttl_hours": settings.audio_ttl_hours,
        "content_type": content_type,
        "extension": extension,
        "search_id": search_id,
        "size_bytes": len(data),
    }
    try:
        file_path.write_bytes(data)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        file_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise
    return audio_id


def _tts_not_found() -> NoReturn:
    raise AppError(404, "AUDIO_NOT_FOUND", TTS_NOT_FOUND_MESSAGE, "audio_download")


def load_tts_audio(audio_id: str) -> tuple[bytes, str]:
    if not TTS_ID_PATTERN.fullmatch(audio_id):
        _tts_not_found()
    meta_path = tts_meta_path(audio_id)
    if not meta_path.is_file():
        _tts_not_found()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        created_at = _parse_created_at(meta["created_at"])
        extension = str(meta["extension"])
        content_type = str(meta["content_type"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        _tts_not_found()
    if _expired(created_at, int(meta.get("ttl_hours") or settings.audio_ttl_hours)):
        _tts_not_found()
    if extension not in TTS_EXTENSIONS:
        _tts_not_found()
    file_path = tts_dir() / f"{audio_id}.{extension}"
    if not file_path.is_file():
        _tts_not_found()
    try:
        return file_path.read_bytes(), content_type
    except OSError:
        _tts_not_found()
