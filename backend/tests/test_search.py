import httpx
import pytest
from fastapi.testclient import TestClient

from config import settings
from errors import AppError
from main import app
from schemas import Midpoint, SearchData
from services import search as search_service
from services.search import choose_geocode, midpoint, parse_amap_distance, poi_distance_m


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "amap_api_key", "test-key")
    return TestClient(app)


def test_midpoint_averages_lng_lat_in_amap_order():
    center = midpoint(120.0, 30.0, 121.0, 32.0)
    assert center.longitude == 120.5
    assert center.latitude == 31.0


def test_missing_amap_distance_uses_haversine_not_zero():
    center = Midpoint(longitude=120.0, latitude=30.0)
    item = {"distance": [], "location": "120.01,30.01"}
    distance = poi_distance_m(item, center)
    assert distance is not None
    assert distance > 0
    assert parse_amap_distance([]) is None
    assert parse_amap_distance("") is None


def test_choose_geocode_ambiguous_when_two_named_places():
    geocodes = [
        {
            "formatted_address": "杭州市西湖区龙翔桥A",
            "city": "杭州市",
            "district": "西湖区",
            "location": "120.16,30.26",
            "level": "公交地铁站点",
        },
        {
            "formatted_address": "杭州市西湖区龙翔桥B",
            "city": "杭州市",
            "district": "西湖区",
            "location": "120.161,30.261",
            "level": "公交地铁站点",
        },
    ]
    with pytest.raises(AppError) as exc:
        choose_geocode(geocodes, city="杭州", address="西湖龙翔桥地铁站")
    assert exc.value.code == "GEOCODE_AMBIGUOUS"


def test_choose_geocode_does_not_merge_300m_neighbors():
    geocodes = [
        {
            "formatted_address": "杭州市上城区杭州东站",
            "city": "杭州市",
            "district": "上城区",
            "location": "120.212,30.291",
            "level": "兴趣点",
        },
        {
            "formatted_address": "杭州市上城区杭州东站西广场",
            "city": "杭州市",
            "district": "上城区",
            "location": "120.211,30.2905",
            "level": "兴趣点",
        },
    ]
    with pytest.raises(AppError) as exc:
        choose_geocode(geocodes, city="杭州", address="杭州东站")
    assert exc.value.code == "GEOCODE_AMBIGUOUS"
    near_m = search_service.haversine_m(120.212, 30.291, 120.211, 30.2905)
    assert near_m < 300


def test_choose_geocode_city_mismatch():
    geocodes = [
        {
            "formatted_address": "上海市黄浦区人民广场",
            "city": "上海市",
            "location": "121.47,31.23",
            "level": "兴趣点",
        }
    ]
    with pytest.raises(AppError) as exc:
        choose_geocode(geocodes, city="杭州", address="人民广场")
    assert exc.value.code == "GEOCODE_CITY_MISMATCH"


def test_search_success_mocked(client, monkeypatch):
    async def fake_search(**kwargs) -> SearchData:
        return SearchData(
            search_id="srch_aaaaaaaaaaaa",
            midpoint=Midpoint(longitude=120.2, latitude=30.27),
            pois=[
                {
                    "name": "示例咖啡",
                    "address": "杭州市上城区示例路1号",
                    "distance_to_midpoint_m": 120.0,
                }
            ],
        )

    monkeypatch.setattr(search_service, "search_meetup", fake_search)
    response = client.post(
        "/search",
        json={
            "city_a": "杭州",
            "address_a": "杭州东站",
            "city_b": "杭州",
            "address_b": "西湖龙翔桥地铁站",
            "category": "咖啡店",
        },
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["search_id"].startswith("srch_") or body["search_id"] == "srch_aaaaaaaaaaaa"
    assert body["midpoint"]["longitude"] == 120.2
    assert len(body["pois"]) == 1


def test_search_no_poi_mocked(client, monkeypatch):
    async def fake_search(**kwargs):
        raise AppError(422, "NO_POI_FOUND", "中点附近没有找到符合条件的店", "search")

    monkeypatch.setattr(search_service, "search_meetup", fake_search)
    response = client.post(
        "/search",
        json={
            "city_a": "杭州",
            "address_a": "杭州东站",
            "city_b": "杭州",
            "address_b": "西湖龙翔桥地铁站",
            "category": "咖啡店",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_POI_FOUND"


def test_search_timeout_mocked(client, monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(search_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    response = client.post(
        "/search",
        json={
            "city_a": "杭州",
            "address_a": "杭州东站",
            "city_b": "杭州",
            "address_b": "西湖龙翔桥地铁站",
            "category": "咖啡店",
        },
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "SEARCH_TIMEOUT"


def test_midpoint_is_geographic_average_only():
    center = midpoint(120.0, 30.0, 120.2, 30.1)
    assert center.longitude == 120.1
    assert center.latitude == 30.05
