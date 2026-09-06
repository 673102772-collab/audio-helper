from __future__ import annotations

import logging

import httpx
from dotenv import dotenv_values

from config import BACKEND_DIR, ENV_PATH, settings
from errors import AppError

logger = logging.getLogger(__name__)
STAGE = "finalize"
PROMPT_PATH = BACKEND_DIR / "prompts" / "reply.txt"
REPLY_FAILED_MESSAGE = "推荐语生成服务异常（阶段：finalize），请稍后重试"
REPLY_TIMEOUT_MESSAGE = "推荐语生成超时（阶段：finalize），请稍后重试"
MISSING_KEY_MESSAGE = "未配置 DEEPSEEK_API_KEY，无法生成推荐语"


def _api_key() -> str:
    memory_key = (settings.deepseek_api_key or "").strip()
    if memory_key:
        return memory_key
    return (dotenv_values(ENV_PATH).get("DEEPSEEK_API_KEY") or "").strip()


def select_broadcast_pois(pois: list[dict]) -> list[dict]:
    for poi in pois:
        name = str(poi.get("name") or "").strip()
        address = str(poi.get("address") or "").strip()
        if name and address:
            return [
                {
                    "name": name,
                    "address": address,
                    "distance_to_midpoint_m": poi.get("distance_to_midpoint_m"),
                }
            ]
    return []


def format_pois_text(pois: list[dict]) -> str:
    lines: list[str] = []
    for index, poi in enumerate(pois, start=1):
        name = str(poi.get("name") or "").strip()
        address = str(poi.get("address") or "").strip()
        distance = poi.get("distance_to_midpoint_m")
        lines.append(f"{index}. {name}，地址：{address}，距中点{distance}米")
    return "\n".join(lines)


def load_reply_prompt(pois: list[dict]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{pois_text}", format_pois_text(pois))


async def generate_reply(pois: list[dict]) -> str:
    selected = select_broadcast_pois(pois)
    if not selected:
        raise AppError(422, "NO_POI_FOUND", "没有可播报的店铺候选，请重新搜索", STAGE)
    first = selected[0]
    name = str(first["name"])
    address = str(first["address"])

    api_key = _api_key()
    if not api_key:
        logger.warning("stage=finalize reason=missing_deepseek_key")
        raise AppError(502, "REPLY_GENERATION_FAILED", MISSING_KEY_MESSAGE, STAGE)

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": load_reply_prompt(selected)},
            {"role": "user", "content": "请根据候选生成播报文字。"},
        ],
        "thinking": {"type": "disabled"},
        "max_tokens": settings.deepseek_reply_max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.deepseek_reply_timeout_s) as client:
            response = await client.post(
                settings.deepseek_chat_url,
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException:
        logger.warning("stage=finalize reason=reply_timeout")
        raise AppError(504, "REPLY_TIMEOUT", REPLY_TIMEOUT_MESSAGE, STAGE) from None
    except httpx.HTTPError:
        logger.warning("stage=finalize reason=reply_http_error")
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE) from None

    if response.status_code >= 400:
        logger.warning("stage=finalize reason=reply_status status=%s", response.status_code)
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)

    try:
        body = response.json()
    except ValueError:
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE) from None
    if not isinstance(body, dict):
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)
    content = message.get("content")
    if not isinstance(content, str):
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)
    text = content.strip()
    if not text:
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)
    if name not in text or address not in text:
        logger.warning("stage=finalize reason=reply_missing_poi_fields")
        raise AppError(502, "REPLY_GENERATION_FAILED", REPLY_FAILED_MESSAGE, STAGE)
    logger.info("stage=finalize reply_len=%s", len(text))
    return text
