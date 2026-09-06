import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile

from config import settings
from errors import AppError
from schemas import ErrorResponse, HealthData, SuccessResponse, UploadData
from services.audio_probe import probe_webm_opus
from services.storage import save_audio

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
