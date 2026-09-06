from __future__ import annotations

import json
import logging
import re
from typing import Any, NoReturn

import httpx
from dotenv import dotenv_values
from pydantic import ValidationError

from config import BACKEND_DIR, ENV_PATH, settings
from errors import AppError
from schemas import ExtractData, ExtractModelOutput

logger = logging.getLogger(__name__)
STAGE = "extract"
EXTRACT_SERVICE_MESSAGE = "信息提取服务异常（阶段：extract），请稍后重试"
EXTRACT_TIMEOUT_MESSAGE = "信息提取服务超时（阶段：extract），请稍后重试"
MODEL_INVALID_MESSAGE = "信息提取服务返回格式异常（阶段：extract），请稍后重试"
MISSING_KEY_MESSAGE = "未配置 DEEPSEEK_API_KEY，无法提取地址信息"
PROMPT_PATH = BACKEND_DIR / "prompts" / "extract.txt"

VAGUE_ADDRESSES = {
    "家",
    "我家",
    "家里",
    "我家里",
    "公司",
    "我公司",
    "单位",
    "办公室",
}

CATEGORY_ALIASES = {
    "喝咖啡": "咖啡店",
    "咖啡": "咖啡店",
    "咖啡馆": "咖啡店",
    "喝茶": "茶馆",
    "茶": "茶馆",
    "吃饭": "餐厅",
    "用餐": "餐厅",
    "餐馆": "餐厅",
}


def _service_error() -> NoReturn:
    raise AppError(502, "EXTRACT_SERVICE_ERROR", EXTRACT_SERVICE_MESSAGE, STAGE)


def _model_invalid() -> NoReturn:
    raise AppError(502, "MODEL_OUTPUT_INVALID", MODEL_INVALID_MESSAGE, STAGE)


def _api_key() -> str:
    memory_key = (settings.deepseek_api_key or "").strip()
    if memory_key:
        return memory_key
    return (dotenv_values(ENV_PATH).get("DEEPSEEK_API_KEY") or "").strip()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _normalize_city(name: str) -> str:
    text = name.strip()
    if text.endswith("市") and len(text) > 1:
        return text[:-1]
    if text.endswith("省") and len(text) > 1:
        return text[:-1]
    return text


def _normalize_category(value: str | None) -> str:
    text = _clean(value)
    if text is None:
        return "咖啡店"
    return CATEGORY_ALIASES.get(text, text)


def _is_vague_address(value: str) -> bool:
    return value in VAGUE_ADDRESSES


def load_extract_prompt(default_city: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{default_city}", default_city)


def parse_model_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, count=1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("stage=extract reason=invalid_json")
        _model_invalid()
    if not isinstance(payload, dict):
        logger.warning("stage=extract reason=json_not_object")
        _model_invalid()
    return payload


def validate_model_output(payload: dict[str, Any]) -> ExtractModelOutput:
    try:
        return ExtractModelOutput.model_validate(payload)
    except ValidationError:
        logger.warning("stage=extract reason=schema_mismatch")
        _model_invalid()


def to_business_result(model: ExtractModelOutput, fallback_city: str) -> ExtractData:
    if model.party_count != 2:
        raise AppError(
            422,
            "PARTY_COUNT_INVALID",
            "当前只支持两个人碰面，请说出两个出发地点",
            STAGE,
        )

    city_a = _clean(model.city_a) or _clean(fallback_city)
    city_b = _clean(model.city_b) or _clean(fallback_city)
    address_a = _clean(model.address_a)
    address_b = _clean(model.address_b)

    if address_a and _is_vague_address(address_a):
        address_a = None
    if address_b and _is_vague_address(address_b):
        address_b = None

    if not address_a or not address_b or not city_a or not city_b:
        raise AppError(
            422,
            "ADDRESS_MISSING",
            "请说出两人各自的具体位置，例如“我在A地，朋友在B地”",
            STAGE,
        )

    if _normalize_city(city_a) != _normalize_city(city_b):
        raise AppError(
            422,
            "CROSS_CITY",
            "两人城市不同，当前只支持同城",
            STAGE,
        )

    return ExtractData(
        city_a=city_a,
        address_a=address_a,
        city_b=city_b,
        address_b=address_b,
        category=_normalize_category(model.category),
    )


async def extract_meetup(text: str, city: str) -> ExtractData:
    api_key = _api_key()
    if not api_key:
        logger.warning("stage=extract reason=missing_api_key")
        raise AppError(502, "EXTRACT_SERVICE_ERROR", MISSING_KEY_MESSAGE, STAGE)

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": load_extract_prompt(city)},
            {"role": "user", "content": f"默认城市：{city}\n用户原话：{text}\n请只输出 json。"},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": settings.deepseek_extract_max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.deepseek_timeout_s) as client:
            response = await client.post(
                settings.deepseek_chat_url,
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException:
        logger.warning("stage=extract reason=timeout")
        raise AppError(504, "EXTRACT_TIMEOUT", EXTRACT_TIMEOUT_MESSAGE, STAGE) from None
    except httpx.HTTPError:
        logger.warning("stage=extract reason=http_error")
        _service_error()

    if response.status_code >= 400:
        logger.warning("stage=extract reason=vendor_status status=%s", response.status_code)
        _service_error()

    try:
        body = response.json()
    except ValueError:
        logger.warning("stage=extract reason=invalid_payload")
        _service_error()
    if not isinstance(body, dict):
        _service_error()

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        logger.warning("stage=extract reason=missing_choices")
        _model_invalid()
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        _model_invalid()
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        logger.warning("stage=extract reason=empty_content")
        _model_invalid()

    parsed = parse_model_content(content)
    model_output = validate_model_output(parsed)
    logger.info(
        "stage=extract party_count=%s has_incomplete=%s",
        model_output.party_count,
        bool(model_output.incomplete_reason),
    )
    return to_business_result(model_output, fallback_city=city)
