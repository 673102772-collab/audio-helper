from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
ENV_PATH = BACKEND_DIR / ".env"
ENV_EXAMPLE_PATH = BACKEND_DIR / ".env.example"
ACTIVATE_PATH = BACKEND_DIR / ".venv" / "bin" / "activate"
PROTECT_ENV_MARKER = "# audio_helper-protect-env"
PROTECT_ENV_SNIPPET = """
# audio_helper-protect-env
if [ -f "$VIRTUAL_ENV/../protect_env.sh" ]; then
  . "$VIRTUAL_ENV/../protect_env.sh"
fi
"""


def ensure_env_file() -> None:
    if ENV_PATH.exists() or not ENV_EXAMPLE_PATH.exists():
        return
    ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def ensure_venv_protects_env() -> None:
    if not ACTIVATE_PATH.is_file():
        return
    text = ACTIVATE_PATH.read_text(encoding="utf-8")
    if PROTECT_ENV_MARKER in text:
        return
    ACTIVATE_PATH.write_text(text.rstrip() + "\n" + PROTECT_ENV_SNIPPET, encoding="utf-8")


ensure_env_file()
ensure_venv_protects_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_origin: str = "http://localhost:5175"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8003

    bailian_api_key: str = ""
    bailian_asr_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    bailian_asr_model: str = "qwen3-asr-flash"
    bailian_tts_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    bailian_tts_model: str = "qwen3-tts-flash"
    bailian_tts_voice: str = "Cherry"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_url: str = "https://api.deepseek.com/chat/completions"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_s: float = 15.0
    deepseek_extract_max_tokens: int = 800
    deepseek_reply_timeout_s: float = 15.0

    amap_api_key: str = ""
    amap_geocode_url: str = "https://restapi.amap.com/v3/geocode/geo"
    amap_around_url: str = "https://restapi.amap.com/v3/place/around"
    amap_geocode_timeout_s: float = 6.0
    amap_poi_timeout_s: float = 8.0
    poi_radius_m: int = 2000
    poi_expand_radius_m: int = 5000
    poi_limit: int = 3
    search_ttl_hours: int = 24

    storage_dir: Path = BACKEND_DIR / "storage"
    audio_ttl_hours: int = 24
    max_audio_bytes: int = 5 * 1024 * 1024
    min_audio_duration_s: float = 1.0
    max_audio_duration_s: float = 60.0
    ffprobe_timeout_s: float = 5.0
    max_asr_base64_bytes: int = 10 * 1024 * 1024
    bailian_asr_timeout_s: float = 30.0
    bailian_asr_language: str = "zh"
    bailian_asr_enable_itn: bool = True
    bailian_tts_language_type: str = "Chinese"
    bailian_tts_timeout_s: float = 20.0
    tts_download_timeout_s: float = 8.0
    deepseek_reply_max_tokens: int = 400
    public_base_url: str = "http://localhost:8003"


settings = Settings()
