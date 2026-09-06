import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from config import settings
from errors import AppError
from main import app
from services import finalize as finalize_service
from services import reply as reply_service
from services import tts as tts_service
from services.reply import load_reply_prompt, select_broadcast_pois
from services.storage import save_search, save_tts_audio, tts_dir, tts_meta_path
from services.tts import DOWNLOAD_WARNING, TTS_WARNING, TtsDegraded, detect_audio_format


WAV_BYTES = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"fmt " + b"\x00" * 8


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "bailian_api_key", "test-key")
    return TestClient(app)


def _save_search(**overrides) -> str:
    payload = {
        "midpoint": {"longitude": 120.2, "latitude": 30.27},
        "pois": [
            {
                "name": "星巴克咖啡(西湖店)",
                "address": "杭州市西湖区示例路1号",
                "distance_to_midpoint_m": 120.0,
            },
            {
                "name": "第二家不应入文",
                "address": "杭州市西湖区示例路2号",
                "distance_to_midpoint_m": 200.0,
            },
        ],
    }
    payload.update(overrides)
    return save_search(payload)


def test_select_broadcast_pois_uses_first_valid_only():
    selected = select_broadcast_pois(
        [
            {"name": "  ", "address": "无效", "distance_to_midpoint_m": 10},
            {
                "name": "星巴克咖啡(西湖店)",
                "address": "杭州市西湖区示例路1号",
                "distance_to_midpoint_m": 120.0,
            },
            {
                "name": "第二家不应入文",
                "address": "杭州市西湖区示例路2号",
                "distance_to_midpoint_m": 200.0,
            },
        ]
    )
    assert selected == [
        {
            "name": "星巴克咖啡(西湖店)",
            "address": "杭州市西湖区示例路1号",
            "distance_to_midpoint_m": 120.0,
        }
    ]
    prompt = load_reply_prompt(selected)
    assert "星巴克咖啡(西湖店)" in prompt
    assert "杭州市西湖区示例路1号" in prompt
    assert "第二家不应入文" not in prompt
    assert "示例路2号" not in prompt


def test_detect_audio_format_uses_magic_not_labels():
    assert detect_audio_format(WAV_BYTES, "audio/mpeg") == ("wav", "audio/wav")
    assert detect_audio_format(b"ID3fake-mp3", "audio/wav") == ("mp3", "audio/mpeg")
    assert detect_audio_format(b"OggSfake", None) == ("ogg", "audio/ogg")
    assert detect_audio_format(b"not-an-audio-file", "audio/wav") is None


def test_finalize_success_mocked(client, monkeypatch):
    search_id = _save_search()
    reply_text = "推荐你们去星巴克咖啡(西湖店)，地址杭州市西湖区示例路1号，距离中点约120米。"

    async def fake_reply(pois: list[dict]) -> str:
        assert pois[0]["name"] == "星巴克咖啡(西湖店)"
        return reply_text

    async def fake_tts(text: str, stored_search_id: str) -> str:
        assert text == reply_text
        assert stored_search_id == search_id
        return save_tts_audio(
            WAV_BYTES,
            content_type="audio/wav",
            extension="wav",
            search_id=stored_search_id,
        )

    monkeypatch.setattr(finalize_service, "generate_reply", fake_reply)
    monkeypatch.setattr(finalize_service, "synthesize_and_store", fake_tts)

    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 200
    body = response.json()
    assert "request_id" in body
    data = body["data"]
    assert data["reply_text"] == reply_text
    assert data["warning"] is None
    assert data["audio_url"].startswith("http://localhost:8003/audio/tts_")

    audio_id = data["audio_url"].rsplit("/", 1)[-1]
    audio = client.get(f"/audio/{audio_id}")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.content == WAV_BYTES
    assert (tts_dir() / f"{audio_id}.wav").is_file()


def test_finalize_tts_degraded_keeps_text(client, monkeypatch):
    search_id = _save_search()
    reply_text = "推荐你们去星巴克咖啡(西湖店)，地址杭州市西湖区示例路1号。"

    async def fake_reply(pois: list[dict]) -> str:
        return reply_text

    async def fake_tts(text: str, stored_search_id: str) -> str:
        raise TtsDegraded(TTS_WARNING)

    monkeypatch.setattr(finalize_service, "generate_reply", fake_reply)
    monkeypatch.setattr(finalize_service, "synthesize_and_store", fake_tts)

    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_text"] == reply_text
    assert data["audio_url"] is None
    assert data["warning"] == TTS_WARNING


def test_finalize_reply_timeout_is_504(client, monkeypatch):
    search_id = _save_search()

    async def fake_reply(pois: list[dict]) -> str:
        raise AppError(504, "REPLY_TIMEOUT", "推荐语生成超时（阶段：finalize），请稍后重试", "finalize")

    monkeypatch.setattr(finalize_service, "generate_reply", fake_reply)
    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 504
    error = response.json()["error"]
    assert error["code"] == "REPLY_TIMEOUT"
    assert error["stage"] == "finalize"


def test_finalize_reply_failed_is_502(client, monkeypatch):
    search_id = _save_search()

    async def fake_reply(pois: list[dict]) -> str:
        raise AppError(502, "REPLY_GENERATION_FAILED", "推荐语生成服务异常（阶段：finalize），请稍后重试", "finalize")

    monkeypatch.setattr(finalize_service, "generate_reply", fake_reply)
    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "REPLY_GENERATION_FAILED"


def test_finalize_search_not_found(client):
    response = client.post("/finalize", json={"search_id": "srch_ffffffffffff"})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "SEARCH_NOT_FOUND"
    assert error["stage"] == "finalize"


def test_finalize_invalid_search_id(client):
    response = client.post("/finalize", json={"search_id": "../secret"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SEARCH_NOT_FOUND"


def test_audio_not_found_returns_json(client):
    response = client.get("/audio/tts_ffffffffffff")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert error["code"] == "AUDIO_NOT_FOUND"
    assert error["stage"] == "audio_download"


def test_audio_upload_id_is_not_served(client):
    response = client.get("/audio/aud_7f3a9c12e4b8")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


def test_audio_expired_returns_json(client):
    audio_id = save_tts_audio(
        WAV_BYTES,
        content_type="audio/wav",
        extension="wav",
        search_id="srch_aaaaaaaaaaaa",
    )
    meta_path = tts_meta_path(audio_id)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    response = client.get(f"/audio/{audio_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


def test_tts_saves_wav_magic_not_url_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "bailian_api_key", "test-key")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={
                    "code": "",
                    "output": {"audio": {"url": "https://example.com/vendor-file.mp3"}},
                },
            )

        async def get(self, *args, **kwargs):
            return httpx.Response(
                200,
                content=WAV_BYTES,
                headers={"content-type": "audio/mpeg"},
            )

    monkeypatch.setattr(tts_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    audio_id = asyncio.run(tts_service.synthesize_and_store("播报文字", "srch_aaaaaaaaaaaa"))
    assert audio_id.startswith("tts_")
    assert (Path(tmp_path) / "tts" / f"{audio_id}.wav").is_file()
    assert not (Path(tmp_path) / "tts" / f"{audio_id}.mp3").exists()
    meta = json.loads((Path(tmp_path) / "tts" / f"{audio_id}.meta.json").read_text(encoding="utf-8"))
    assert meta["content_type"] == "audio/wav"
    assert meta["extension"] == "wav"


def test_tts_download_timeout_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "bailian_api_key", "test-key")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={"output": {"audio": {"url": "https://example.com/file.wav"}}},
            )

        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(tts_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    with pytest.raises(TtsDegraded) as exc:
        asyncio.run(tts_service.synthesize_and_store("播报文字", "srch_aaaaaaaaaaaa"))
    assert exc.value.warning == DOWNLOAD_WARNING


def test_generate_reply_prompt_contains_only_first_shop(monkeypatch):
    captured: dict = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            captured["json"] = kwargs.get("json")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "推荐你们去星巴克咖啡(西湖店)，地址杭州市西湖区示例路1号。"
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(reply_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    text = asyncio.run(
        reply_service.generate_reply(
            [
                {
                    "name": "星巴克咖啡(西湖店)",
                    "address": "杭州市西湖区示例路1号",
                    "distance_to_midpoint_m": 120.0,
                },
                {
                    "name": "第二家不应入文",
                    "address": "杭州市西湖区示例路2号",
                    "distance_to_midpoint_m": 200.0,
                },
            ]
        )
    )
    assert "星巴克咖啡(西湖店)" in text
    payload = captured["json"]
    system = payload["messages"][0]["content"]
    assert "星巴克咖啡(西湖店)" in system
    assert "杭州市西湖区示例路1号" in system
    assert "第二家不应入文" not in system
    assert "response_format" not in payload
    assert payload["thinking"] == {"type": "disabled"}


def test_reply_timeout_mocked(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(reply_service.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    with pytest.raises(AppError) as exc:
        asyncio.run(
            reply_service.generate_reply(
                [
                    {
                        "name": "星巴克咖啡(西湖店)",
                        "address": "杭州市西湖区示例路1号",
                        "distance_to_midpoint_m": 120.0,
                    }
                ]
            )
        )
    assert exc.value.status_code == 504
    assert exc.value.code == "REPLY_TIMEOUT"


def test_finalize_missing_search_id_validation(client):
    response = client.post("/finalize", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["stage"] == "finalize"
