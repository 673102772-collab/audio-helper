import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Path as PathParam, Request, UploadFile
from fastapi.responses import Response

from config import settings
from errors import AppError
from schemas import AsrData, AsrRequest, ErrorResponse, ExtractData, ExtractRequest, FinalizeData, FinalizeRequest, HealthData, SearchData, SearchRequest, SuccessResponse, UploadData
from services import asr as asr_service
from services import extract as extract_service
from services import finalize as finalize_service
from services import search as search_service
from services.audio_probe import probe_webm_opus
from services.storage import load_audio, load_tts_audio, save_audio

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


@router.post(
    "/search",
    response_model=SuccessResponse[SearchData],
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def search(request: Request, body: SearchRequest) -> SuccessResponse[SearchData]:
    logger.info(
        "stage=search city_a=%s city_b=%s category=%s",
        body.city_a,
        body.city_b,
        body.category,
    )
    data = await search_service.search_meetup(
        city_a=body.city_a,
        address_a=body.address_a,
        city_b=body.city_b,
        address_b=body.address_b,
        category=body.category,
    )
    logger.info("stage=search result=ok search_id=%s poi_count=%s", data.search_id, len(data.pois))
    return SuccessResponse(
        request_id=_request_id(request),
        data=data,
    )


@router.post(
    "/finalize",
    response_model=SuccessResponse[FinalizeData],
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def finalize(request: Request, body: FinalizeRequest) -> SuccessResponse[FinalizeData]:
    logger.info("stage=finalize search_id=%s", body.search_id)
    data = await finalize_service.finalize_search(body.search_id)
    logger.info(
        "stage=finalize result=ok has_audio=%s warning=%s",
        data.audio_url is not None,
        bool(data.warning),
    )
    return SuccessResponse(
        request_id=_request_id(request),
        data=data,
    )


@router.get(
    "/audio/{audio_id}",
    response_class=Response,
    responses={
        200: {
            "content": {
                "audio/wav": {},
                "audio/mpeg": {},
                "audio/ogg": {},
            }
        },
        404: {"model": ErrorResponse},
    },
)
async def download_audio(
    audio_id: str = PathParam(..., examples=["tts_9d2b4e7c1a5f"]),
) -> Response:
    data, content_type = load_tts_audio(audio_id)
    logger.info("stage=audio_download audio_id=%s content_type=%s size_bytes=%s", audio_id, content_type, len(data))
    return Response(content=data, media_type=content_type)
