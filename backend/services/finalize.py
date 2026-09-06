from __future__ import annotations

import logging

from config import settings
from errors import AppError
from schemas import FinalizeData, PoiItem
from services.reply import generate_reply
from services.storage import load_search
from services.tts import TtsDegraded, synthesize_and_store

logger = logging.getLogger(__name__)


def _pois_from_record(record: dict) -> list[dict]:
    raw = record.get("pois")
    if not isinstance(raw, list):
        return []
    pois: list[dict] = []
    for item in raw:
        try:
            parsed = PoiItem.model_validate(item)
        except Exception:
            continue
        pois.append(parsed.model_dump())
    return pois


async def finalize_search(search_id: str) -> FinalizeData:
    record = load_search(search_id)
    pois = _pois_from_record(record)
    reply_text = await generate_reply(pois)
    if not reply_text.strip():
        raise AppError(502, "REPLY_GENERATION_FAILED", "推荐语生成服务异常（阶段：finalize），请稍后重试", "finalize")

    try:
        audio_id = await synthesize_and_store(reply_text, search_id)
    except TtsDegraded as exc:
        logger.warning("stage=finalize tts_degraded")
        return FinalizeData(reply_text=reply_text, audio_url=None, warning=exc.warning)

    audio_url = f"{settings.public_base_url.rstrip('/')}/audio/{audio_id}"
    return FinalizeData(reply_text=reply_text, audio_url=audio_url, warning=None)
