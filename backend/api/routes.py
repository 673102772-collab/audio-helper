import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile

from config import settings
from errors import AppError
from schemas import AsrData, AsrRequest, ErrorResponse, ExtractData, ExtractRequest, HealthData, SuccessResponse, UploadData
from services import asr as asr_service
from services import extract as extract_service
from services.audio_probe import probe_webm_opus
from services.storage import load_audio, save_audio

logger = logging.getLogger(__name__)
router = APIRouter()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid4())


@router.get("/health", response_model=SuccessResponse[HealthData])
def health(request: Request) -> SuccessResponse[HealthData]:
    return SuccessResponse(
        request_id=_request_id(request),
        data=HealthData(status="ok"),
    )


@router.post(
    "/upload",
    response_model=SuccessResponse[UploadData],
    responses={
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def upload(request: Request, file: UploadFile = File(...)) -> SuccessResponse[UploadData]:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_audio_bytes:
            raise AppError(
                413,
                "FILE_TOO_LARGE",
                "录音文件过大，请控制在 5 MB 以内",
                "upload",
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise AppError(
            422,
            "AUDIO_PARSE_FAILED",
            "音频文件损坏或格式异常，请重新录音",
            "upload",
        )

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_file:
            temp_file.write(data)
            temp_path = Path(temp_file.name)
        probe = probe_webm_opus(temp_path, len(data))
        audio_id = save_audio(
            data,
            container=probe.container,
            codec=probe.codec,
            duration_s=probe.duration_s,
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    logger.info(
        "stage=upload audio_id=%s size_bytes=%s duration_s=%.3f",
        audio_id,
        probe.size_bytes,
        probe.duration_s,
    )
    return SuccessResponse(
        request_id=_request_id(request),
        data=UploadData(audio_id=audio_id),
    )


@router.post(
    "/asr",
    response_model=SuccessResponse[AsrData],
    responses={
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def asr(request: Request, body: AsrRequest) -> SuccessResponse[AsrData]:
    audio_bytes = load_audio(body.audio_id, stage="asr")
    logger.info("stage=asr audio_id=%s size_bytes=%s", body.audio_id, len(audio_bytes))
    text = await asr_service.transcribe(audio_bytes)
    logger.info("stage=asr audio_id=%s result=ok text_len=%s", body.audio_id, len(text))
    return SuccessResponse(
        request_id=_request_id(request),
        data=AsrData(text=text),
    )


@router.post(
    "/extract",
    response_model=SuccessResponse[ExtractData],
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def extract(request: Request, body: ExtractRequest) -> SuccessResponse[ExtractData]:
    logger.info("stage=extract text_len=%s city=%s", len(body.text), body.city)
    data = await extract_service.extract_meetup(body.text, body.city)
    logger.info("stage=extract result=ok category=%s", data.category)
    return SuccessResponse(
        request_id=_request_id(request),
        data=data,
    )
