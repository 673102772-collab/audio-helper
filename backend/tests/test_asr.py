import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app
from services import asr as asr_service
from services.storage import audio_file_path, audio_meta_path, save_audio


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "bailian_api_key", "test-key")
    return TestClient(app)


def _save_sample() -> str:
    return save_audio(
        b"fake-webm-bytes",
        container="matroska,webm",
        codec="opus",
        duration_s=2.0,
    )


def test_asr_audio_not_found(client):
    response = client.post("/asr", json={"audio_id": "aud_ffffffffffff"})
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "AUDIO_NOT_FOUND"
    assert body["error"]["stage"] == "asr"
    assert "request_id" in body


def test_asr_invalid_audio_id(client):
    response = client.post("/asr", json={"audio_id": "../secret"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


def test_asr_missing_field(client):
    response = client.post("/asr", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["stage"] == "asr"


def test_asr_expired(client):
    audio_id = _save_sample()
    meta_path = audio_meta_path(audio_id)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert audio_file_path(audio_id).is_file()

    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


def test_asr_success_mocked(client, monkeypatch):
    audio_id = _save_sample()

    async def fake_transcribe(audio_bytes: bytes) -> str:
        assert audio_bytes == b"fake-webm-bytes"
        return "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店"

    monkeypatch.setattr(asr_service, "transcribe", fake_transcribe)
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["text"].startswith("我在杭州东站")
    assert "request_id" in body


def test_asr_empty_result_mocked(client, monkeypatch):
    audio_id = _save_sample()

    async def fake_transcribe(audio_bytes: bytes) -> str:
        from errors import AppError

        raise AppError(
            422,
            "ASR_EMPTY_RESULT",
            "未能识别到有效内容，请在安静环境重新录音",
            "asr",
        )

    monkeypatch.setattr(asr_service, "transcribe", fake_transcribe)
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASR_EMPTY_RESULT"


def test_asr_timeout_mocked(client, monkeypatch):
    audio_id = _save_sample()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(asr_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ASR_TIMEOUT"


def test_asr_missing_api_key(client, monkeypatch):
    audio_id = _save_sample()
    monkeypatch.setattr(settings, "bailian_api_key", "")
    monkeypatch.setattr(asr_service, "dotenv_values", lambda _path: {})
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "ASR_SERVICE_ERROR"
    assert "BAILIAN_API_KEY" in body["error"]["message"]


def test_asr_vendor_error_mocked(client, monkeypatch):
    audio_id = _save_sample()

    class FakeResponse:
        status_code = 500

        def json(self):
            return {"code": "InternalError"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(asr_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ASR_SERVICE_ERROR"
