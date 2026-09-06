from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
