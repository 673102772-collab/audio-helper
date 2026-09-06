from __future__ import annotations

import logging
import math
import re
from typing import Any, NoReturn

import httpx
from dotenv import dotenv_values

from config import ENV_PATH, settings
from errors import AppError
from schemas import Midpoint, PoiItem, SearchData
from services.storage import save_search

logger = logging.getLogger(__name__)
STAGE = "search"
MISSING_KEY_MESSAGE = "未配置 AMAP_API_KEY，无法查询地点"
GEOCODE_ERROR_MESSAGE = "地图服务异常（阶段：geocoding），请稍后重试"
POI_ERROR_MESSAGE = "地图服务异常（阶段：poi_search），请稍后重试"
TIMEOUT_MESSAGE = "地图查询超时（阶段：search），请稍后重试"
AMBIGUOUS_MESSAGE = "地点匹配到多个不同位置，请补充更具体的地点"
CITY_MISMATCH_MESSAGE = "定位结果与城市不符"
NO_POI_MESSAGE = "中点附近没有找到符合条件的店"
COARSE_LEVELS = {"国家", "省", "市", "区县", "开发区", "未知"}
EARTH_RADIUS_M = 6_371_000


def _timeout() -> NoReturn:
    raise AppError(504, "SEARCH_TIMEOUT", TIMEOUT_MESSAGE, STAGE)


def _geocode_service_error() -> NoReturn:
    raise AppError(502, "GEOCODE_SERVICE_ERROR", GEOCODE_ERROR_MESSAGE, STAGE)


def _poi_service_error() -> NoReturn:
    raise AppError(502, "POI_SERVICE_ERROR", POI_ERROR_MESSAGE, STAGE)


def _api_key() -> str:
    memory_key = (settings.amap_api_key or "").strip()
    if memory_key:
        return memory_key
    return (dotenv_values(ENV_PATH).get("AMAP_API_KEY") or "").strip()


def amap_text(value: Any) -> str:
    if value is None or isinstance(value, list):
        return ""
    return str(value).strip()


def parse_location(value: Any) -> tuple[float, float] | None:
    text = amap_text(value)
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError:
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    return longitude, latitude


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def midpoint(lng_a: float, lat_a: float, lng_b: float, lat_b: float) -> Midpoint:
    return Midpoint(longitude=(lng_a + lng_b) / 2, latitude=(lat_a + lat_b) / 2)


def _normalize_city(name: str) -> str:
    text = name.strip()
    if text.endswith("市") and len(text) > 1:
        return text[:-1]
    if text.endswith("省") and len(text) > 1:
        return text[:-1]
    return text


def _geocode_city(item: dict[str, Any]) -> str:
    city = amap_text(item.get("city"))
    if city:
        return city
    return amap_text(item.get("province"))


def _city_matches(item: dict[str, Any], expected_city: str) -> bool:
    expected = _normalize_city(expected_city)
    if not expected:
        return False
    actual = _normalize_city(_geocode_city(item))
    formatted = amap_text(item.get("formatted_address"))
    return expected == actual or expected in formatted


def _query_core(address: str, city: str) -> str:
    core = address.strip()
    for token in (city, _normalize_city(city)):
        core = core.replace(token, "")
    core = re.sub(r"(地铁站|公交站|火车站|高铁站)$", "", core)
    return core.strip()


def _name_matches(item: dict[str, Any], address: str, city: str) -> bool:
    blob = "".join(
        [
            amap_text(item.get("formatted_address")),
            amap_text(item.get("district")),
            amap_text(item.get("street")),
            amap_text(item.get("number")),
        ]
    )
    if not blob:
        return False
    if address in blob:
        return True
    core = _query_core(address, city)
    if len(core) < 2:
        return True
    return core in blob


def parse_amap_distance(value: Any) -> float | None:
    text = amap_text(value)
    if not text:
        return None
    try:
        distance = float(text)
    except ValueError:
        return None
    if not math.isfinite(distance) or distance < 0:
        return None
    return distance


def poi_distance_m(item: dict[str, Any], center: Midpoint) -> float | None:
    reported = parse_amap_distance(item.get("distance"))
    if reported is not None:
        return reported
    location = parse_location(item.get("location"))
    if location is None:
        return None
    return haversine_m(center.longitude, center.latitude, location[0], location[1])


def _dedupe_same_point(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in items:
        loc = parse_location(item.get("location"))
        if loc is None:
            continue
        duplicate = False
        for existing in kept:
            existing_loc = parse_location(existing.get("location"))
            if existing_loc is None:
                continue
            if haversine_m(loc[0], loc[1], existing_loc[0], existing_loc[1]) < 1:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def choose_geocode(geocodes: list[Any], *, city: str, address: str) -> dict[str, Any]:
    if not isinstance(geocodes, list) or not geocodes:
        raise AppError(422, "GEOCODE_AMBIGUOUS", AMBIGUOUS_MESSAGE, STAGE)

    parsed: list[dict[str, Any]] = [item for item in geocodes if isinstance(item, dict)]
    with_location = []
    for item in parsed:
        if parse_location(item.get("location")) is None:
            continue
        with_location.append(item)
    if not with_location:
        raise AppError(422, "GEOCODE_AMBIGUOUS", AMBIGUOUS_MESSAGE, STAGE)

    in_city = [item for item in with_location if _city_matches(item, city)]
    if not in_city:
        raise AppError(422, "GEOCODE_CITY_MISMATCH", CITY_MISMATCH_MESSAGE, STAGE)

    leveled = [item for item in in_city if amap_text(item.get("level")) not in COARSE_LEVELS]
    if not leveled:
        raise AppError(422, "GEOCODE_AMBIGUOUS", AMBIGUOUS_MESSAGE, STAGE)

    named = [item for item in leveled if _name_matches(item, address, city)]
    pool = named or leveled
    pool = _dedupe_same_point(pool)
    if len(pool) != 1:
        logger.info("stage=search reason=ambiguous count=%s address=%s", len(pool), address)
        raise AppError(422, "GEOCODE_AMBIGUOUS", AMBIGUOUS_MESSAGE, STAGE)
    return pool[0]


async def _amap_get(url: str, params: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException:
        logger.warning("stage=search reason=timeout url_host=amap")
        _timeout()
    except httpx.HTTPError:
        logger.warning("stage=search reason=http_error")
        _geocode_service_error()
    if response.status_code >= 400:
        logger.warning("stage=search reason=vendor_status status=%s", response.status_code)
        _geocode_service_error()
    try:
        body = response.json()
    except ValueError:
        _geocode_service_error()
    if not isinstance(body, dict):
        _geocode_service_error()
    return body


async def geocode_address(city: str, address: str) -> tuple[float, float, str]:
    key = _api_key()
    if not key:
        raise AppError(502, "GEOCODE_SERVICE_ERROR", MISSING_KEY_MESSAGE, STAGE)
    body = await _amap_get(
        settings.amap_geocode_url,
        {"key": key, "address": address, "city": city, "output": "JSON"},
        settings.amap_geocode_timeout_s,
    )
    if amap_text(body.get("status")) != "1":
        logger.warning("stage=search reason=geocode_status")
        _geocode_service_error()
    chosen = choose_geocode(body.get("geocodes") or [], city=city, address=address)
    location = parse_location(chosen.get("location"))
    if location is None:
        raise AppError(422, "GEOCODE_AMBIGUOUS", AMBIGUOUS_MESSAGE, STAGE)
    return location[0], location[1], amap_text(chosen.get("level"))


def _valid_poi(item: Any, center: Midpoint) -> PoiItem | None:
    if not isinstance(item, dict):
        return None
    name = amap_text(item.get("name"))
    address = amap_text(item.get("address"))
    if not name or not address:
        return None
    if parse_location(item.get("location")) is None:
        return None
    distance = poi_distance_m(item, center)
    if distance is None:
        return None
    return PoiItem(name=name, address=address, distance_to_midpoint_m=round(distance, 1))


async def search_pois(center: Midpoint, category: str, radius_m: int) -> list[PoiItem]:
    key = _api_key()
    if not key:
        raise AppError(502, "POI_SERVICE_ERROR", MISSING_KEY_MESSAGE, STAGE)
    try:
        async with httpx.AsyncClient(timeout=settings.amap_poi_timeout_s) as client:
            response = await client.get(
                settings.amap_around_url,
                params={
                    "key": key,
                    "location": f"{center.longitude:.6f},{center.latitude:.6f}",
                    "keywords": category,
                    "radius": radius_m,
                    "offset": 20,
                    "page": 1,
                    "extensions": "base",
                },
            )
    except httpx.TimeoutException:
        logger.warning("stage=search reason=poi_timeout radius=%s", radius_m)
        _timeout()
    except httpx.HTTPError:
        logger.warning("stage=search reason=poi_http_error")
        _poi_service_error()
    if response.status_code >= 400:
        logger.warning("stage=search reason=poi_status status=%s", response.status_code)
        _poi_service_error()
    try:
        body = response.json()
    except ValueError:
        _poi_service_error()
    if not isinstance(body, dict) or amap_text(body.get("status")) != "1":
        logger.warning("stage=search reason=poi_business_status")
        _poi_service_error()

    pois: list[PoiItem] = []
    for item in body.get("pois") or []:
        parsed = _valid_poi(item, center)
        if parsed is not None:
            pois.append(parsed)
    pois.sort(key=lambda poi: poi.distance_to_midpoint_m)
    return pois[: settings.poi_limit]


async def search_meetup(
    *,
    city_a: str,
    address_a: str,
    city_b: str,
    address_b: str,
    category: str,
) -> SearchData:
    lng_a, lat_a, level_a = await geocode_address(city_a, address_a)
    lng_b, lat_b, level_b = await geocode_address(city_b, address_b)
    center = midpoint(lng_a, lat_a, lng_b, lat_b)
    logger.info(
        "stage=search midpoint_lng=%.6f midpoint_lat=%.6f level_a=%s level_b=%s",
        center.longitude,
        center.latitude,
        level_a,
        level_b,
    )
    pois = await search_pois(center, category, settings.poi_radius_m)
    used_radius = settings.poi_radius_m
    if not pois:
        logger.info("stage=search expand_radius=%s", settings.poi_expand_radius_m)
        pois = await search_pois(center, category, settings.poi_expand_radius_m)
        used_radius = settings.poi_expand_radius_m
    if not pois:
        raise AppError(422, "NO_POI_FOUND", NO_POI_MESSAGE, STAGE)

    search_id = save_search(
        {
            "city_a": city_a,
            "address_a": address_a,
            "city_b": city_b,
            "address_b": address_b,
            "category": category,
            "radius_m": used_radius,
            "point_a": {"longitude": lng_a, "latitude": lat_a, "level": level_a},
            "point_b": {"longitude": lng_b, "latitude": lat_b, "level": level_b},
            "midpoint": center.model_dump(),
            "pois": [poi.model_dump() for poi in pois],
        }
    )
    return SearchData(search_id=search_id, midpoint=center, pois=pois)
