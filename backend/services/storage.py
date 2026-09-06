from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import settings


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
