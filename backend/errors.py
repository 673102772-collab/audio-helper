from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from schemas import ErrorDetail, ErrorResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, stage: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.stage = stage


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id
    request_id = str(uuid4())
    request.state.request_id = request_id
    return request_id


def error_response(request: Request, status_code: int, code: str, message: str, stage: str) -> JSONResponse:
    payload = ErrorResponse(
        request_id=get_request_id(request),
        error=ErrorDetail(code=code, message=message, stage=stage),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.stage)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        stage = "upload" if request.url.path.rstrip("/") == "/upload" else "request"
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "请求参数不正确",
            stage,
        )
