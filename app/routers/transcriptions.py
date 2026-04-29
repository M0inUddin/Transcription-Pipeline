from collections.abc import Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.core.config import get_settings
from app.core.errors import AudioValidationError
from app.schemas import QueuedTranscriptionResponse, TranscriptionResponse
from app.services import TranscriptionService
from app.dependencies import get_transcription_service

router = APIRouter(prefix="/transcriptions", tags=["transcriptions"])


@router.post(
    "",
    response_model=QueuedTranscriptionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_transcription(
    request: Request,
    file: UploadFile | None = File(default=None),
    audio_url: str | None = Form(default=None),
    audio_base64: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    mime_type: str | None = Form(default=None),
    service: TranscriptionService = Depends(get_transcription_service),
) -> QueuedTranscriptionResponse:
    file_bytes: bytes | None = None
    content_type = request.headers.get("content-type", "").lower()

    if content_type.startswith("application/json"):
        try:
            body = await request.json()
        except ValueError as exc:
            raise AudioValidationError("Request body is not valid JSON.") from exc
        if not isinstance(body, Mapping):
            raise AudioValidationError("JSON request body must be an object.")
        audio_url = body.get("audio_url") or body.get("url")
        audio_base64 = body.get("audio_base64")
        filename = body.get("filename")
        mime_type = body.get("mime_type")
    elif file is not None:
        settings = get_settings()
        file_bytes = await file.read(settings.max_audio_bytes + 1)
        filename = filename or file.filename
        mime_type = mime_type or file.content_type

    return service.create_job(
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        audio_url=audio_url,
        audio_base64=audio_base64,
    )


@router.get("/{job_id}", response_model=TranscriptionResponse)
def get_transcription(
    job_id: UUID,
    service: TranscriptionService = Depends(get_transcription_service),
) -> TranscriptionResponse:
    return service.get_job(job_id)
