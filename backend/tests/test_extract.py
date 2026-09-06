import httpx
import pytest
from fastapi.testclient import TestClient

from config import settings
from errors import AppError
from main import app
from schemas import ExtractData, ExtractModelOutput
from services import extract as extract_service


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    return TestClient(app)


def test_extract_success_mocked(client, monkeypatch):
    async def fake_extract(text: str, city: str) -> ExtractData:
        assert "杭州东站" in text
        assert city == "杭州"
        return ExtractData(
            city_a="杭州",
            address_a="杭州东站",
            city_b="杭州",
            address_b="西湖龙翔桥地铁站",
            category="咖啡店",
        )

    monkeypatch.setattr(extract_service, "extract_meetup", fake_extract)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"] == {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "address_b": "西湖龙翔桥地铁站",
        "category": "咖啡店",
    }


def test_extract_party_count_invalid():
    model = ExtractModelOutput(
        city_a="杭州",
        address_a="杭州东站",
        city_b="杭州",
        address_b="龙翔桥",
        category="咖啡店",
        party_count=3,
        incomplete_reason="三个人",
    )
    with pytest.raises(AppError) as exc:
        extract_service.to_business_result(model, fallback_city="杭州")
    assert exc.value.status_code == 422
    assert exc.value.code == "PARTY_COUNT_INVALID"


def test_extract_address_missing():
    model = ExtractModelOutput(
        city_a="上海",
        address_a="人民广场",
        city_b=None,
        address_b=None,
        category="咖啡店",
        party_count=2,
        incomplete_reason="缺乙方",
    )
    with pytest.raises(AppError) as exc:
        extract_service.to_business_result(model, fallback_city="杭州")
    assert exc.value.code == "ADDRESS_MISSING"


def test_extract_vague_home_address():
    model = ExtractModelOutput(
        city_a="杭州",
        address_a="我家",
        city_b="杭州",
        address_b="公司",
        category="咖啡店",
        party_count=2,
        incomplete_reason="含糊",
    )
    with pytest.raises(AppError) as exc:
        extract_service.to_business_result(model, fallback_city="杭州")
    assert exc.value.code == "ADDRESS_MISSING"


def test_extract_cross_city():
    model = ExtractModelOutput(
        city_a="杭州",
        address_a="杭州东站",
        city_b="上海",
        address_b="人民广场",
        category="咖啡店",
        party_count=2,
        incomplete_reason="跨城",
    )
    with pytest.raises(AppError) as exc:
        extract_service.to_business_result(model, fallback_city="杭州")
    assert exc.value.code == "CROSS_CITY"


def test_extract_default_city_and_category():
    model = ExtractModelOutput(
        city_a=None,
        address_a="杭州东站",
        city_b=None,
        address_b="龙翔桥地铁站",
        category="喝咖啡",
        party_count=2,
        incomplete_reason=None,
    )
    result = extract_service.to_business_result(model, fallback_city="杭州")
    assert result.city_a == "杭州"
    assert result.city_b == "杭州"
    assert result.category == "咖啡店"


def test_extract_same_city_with_suffix():
    model = ExtractModelOutput(
        city_a="杭州市",
        address_a="杭州东站",
        city_b="杭州",
        address_b="龙翔桥地铁站",
        category="咖啡店",
        party_count=2,
        incomplete_reason=None,
    )
    result = extract_service.to_business_result(model, fallback_city="杭州")
    assert result.city_a == "杭州市"
    assert result.city_b == "杭州"


def test_extract_invalid_json_is_model_error():
    with pytest.raises(AppError) as exc:
        extract_service.parse_model_content("不是json")
    assert exc.value.status_code == 502
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_extract_missing_field_is_model_error():
    with pytest.raises(AppError) as exc:
        extract_service.validate_model_output({"city_a": "杭州"})
    assert exc.value.status_code == 502
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_extract_timeout_mocked(client, monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(extract_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥，找个咖啡店", "city": "杭州"},
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "EXTRACT_TIMEOUT"
