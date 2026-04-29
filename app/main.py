from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import (
    AudioValidationError,
    ConfigurationError,
    JobNotFoundError,
    PermanentProviderError,
    PipelineError,
    QueueingError,
    StorageError,
    TransientProcessingError,
    TransientProviderError,
)
from app.routers.health import router as health_router
from app.routers.transcriptions import router as transcriptions_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Async FastAPI transcription pipeline backed by Deepgram, Supabase, Celery, and Redis.",
    )
    app.include_router(health_router)
    app.include_router(transcriptions_router)
    app.add_exception_handler(PipelineError, pipeline_error_handler)
    return app


async def pipeline_error_handler(_: Request, exc: PipelineError) -> JSONResponse:
    status_code = _status_code_for_error(exc)
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": getattr(exc, "code", "pipeline_error"),
                "message": getattr(exc, "message", str(exc)),
                "retryable": bool(getattr(exc, "retryable", False)),
            }
        },
    )


def _status_code_for_error(exc: PipelineError) -> int:
    if exc.status_code:
        return exc.status_code
    if isinstance(exc, AudioValidationError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, JobNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(
        exc,
        (
            ConfigurationError,
            StorageError,
            QueueingError,
            TransientProcessingError,
            TransientProviderError,
        ),
    ):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, PermanentProviderError):
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_500_INTERNAL_SERVER_ERROR


app = create_app()
