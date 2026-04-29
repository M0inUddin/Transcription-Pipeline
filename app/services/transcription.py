from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.errors import (
    AudioValidationError,
    JobNotFoundError,
    PermanentProcessingError,
    QueueingError,
)
from app.providers import DeepgramProvider
from app.schemas import (
    ErrorInfo,
    InputSource,
    JobStatus,
    QueuedTranscriptionResponse,
    TranscriptionJob,
    TranscriptionResponse,
)
from app.storage.base import StorageRepository
from app.utils.audio import (
    decode_base64_audio,
    download_remote_audio,
    validate_audio_bytes,
    validate_remote_url,
    validate_single_input,
)

TaskSender = Callable[[str], None]


class TranscriptionService:
    def __init__(
        self,
        repository: StorageRepository,
        *,
        settings: Settings | None = None,
        task_sender: TaskSender | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or get_settings()
        self.task_sender = task_sender or enqueue_transcription_task

    def create_job(
        self,
        *,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
        audio_url: str | None = None,
        audio_base64: str | None = None,
    ) -> QueuedTranscriptionResponse:
        validate_single_input(
            has_file=file_bytes is not None,
            audio_url=audio_url,
            audio_base64=audio_base64,
        )

        if file_bytes is not None:
            job = self._create_bytes_job(
                data=file_bytes,
                filename=filename,
                mime_type=mime_type,
                source_type=InputSource.file,
            )
        elif audio_base64:
            decoded, data_uri_mime_type = decode_base64_audio(audio_base64)
            job = self._create_bytes_job(
                data=decoded,
                filename=filename,
                mime_type=data_uri_mime_type or mime_type,
                source_type=InputSource.base64,
            )
        else:
            job = self._create_url_job(audio_url or "")

        try:
            self.task_sender(str(job.job_id))
        except Exception as exc:
            error = ErrorInfo(
                code="queueing_error",
                message="Failed to enqueue transcription job for background processing.",
                retryable=True,
            )
            try:
                self.repository.update_job(
                    str(job.job_id),
                    {
                        "status": JobStatus.failed,
                        "error": error,
                    },
                )
            except Exception:
                pass
            raise QueueingError(error.message) from exc
        return QueuedTranscriptionResponse(
            job_id=job.job_id, status=JobStatus.queued, provider=job.provider
        )

    def get_job(self, job_id: str | UUID) -> TranscriptionResponse:
        job = self.repository.get_job(str(job_id))
        if not job:
            raise JobNotFoundError(f"Transcription job {job_id} was not found.")
        return job.to_response()

    def _create_bytes_job(
        self,
        *,
        data: bytes,
        filename: str | None,
        mime_type: str | None,
        source_type: InputSource,
    ) -> TranscriptionJob:
        metadata = validate_audio_bytes(
            data,
            filename=filename,
            declared_mime_type=mime_type,
            max_bytes=self.settings.max_audio_bytes,
            max_seconds=self.settings.max_audio_seconds,
        )
        job = TranscriptionJob(
            status=JobStatus.queued,
            source_type=source_type,
            filename=metadata.filename,
            mime_type=metadata.mime_type,
            size_bytes=metadata.size_bytes,
            duration_seconds=metadata.duration_seconds,
        )
        job.audio_path = self.repository.upload_audio(
            str(job.job_id),
            metadata.filename,
            data,
            metadata.mime_type,
        )
        return self.repository.create_job(job)

    def _create_url_job(self, audio_url: str) -> TranscriptionJob:
        validated_url = validate_remote_url(audio_url)
        job = TranscriptionJob(
            status=JobStatus.queued,
            source_type=InputSource.remote_url,
            source_url=validated_url,
        )
        return self.repository.create_job(job)


class TranscriptionProcessor:
    def __init__(
        self,
        repository: StorageRepository,
        provider: DeepgramProvider,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.settings = settings or get_settings()

    def process_job(self, job_id: str | UUID) -> TranscriptionJob:
        job = self.repository.get_job(str(job_id))
        if not job:
            raise JobNotFoundError(f"Transcription job {job_id} was not found.")
        if JobStatus(job.status) == JobStatus.completed:
            return job

        job = self.repository.update_job(
            str(job.job_id),
            {
                "status": JobStatus.processing,
                "error": None,
            },
        )

        if (
            InputSource(job.source_type) == InputSource.remote_url
            and not job.audio_path
        ):
            job = self._materialize_remote_audio(job)

        if not job.audio_path:
            raise PermanentProcessingError(
                "Job does not have an audio object to transcribe."
            )

        audio = self.repository.download_audio(job.audio_path)
        result = self.provider.transcribe_bytes(
            audio, job.mime_type or "application/octet-stream"
        )
        transcript_path = self.repository.upload_transcript(
            str(job.job_id),
            {
                "job_id": str(job.job_id),
                "provider": result.provider,
                "provider_request_id": result.provider_request_id,
                "text": result.text,
                "segments": [
                    segment.model_dump(mode="json") for segment in result.segments
                ],
                "words": [word.model_dump(mode="json") for word in result.words],
                "detected_language": result.detected_language,
                "language_confidence": result.language_confidence,
                "raw_response": result.raw_response,
            },
        )

        return self.repository.update_job(
            str(job.job_id),
            {
                "status": JobStatus.completed,
                "text": result.text,
                "segments": result.segments,
                "words": result.words,
                "detected_language": result.detected_language,
                "language_confidence": result.language_confidence,
                "provider_request_id": result.provider_request_id,
                "transcript_path": transcript_path,
                "error": None,
                "completed_at": datetime.now(UTC),
            },
        )

    def _materialize_remote_audio(self, job: TranscriptionJob) -> TranscriptionJob:
        if not job.source_url:
            raise AudioValidationError("Remote URL job is missing source_url.")

        data, filename, mime_type = download_remote_audio(
            str(job.source_url),
            max_bytes=self.settings.max_audio_bytes,
            timeout_seconds=self.settings.remote_download_timeout_seconds,
        )
        metadata = validate_audio_bytes(
            data,
            filename=filename,
            declared_mime_type=mime_type,
            max_bytes=self.settings.max_audio_bytes,
            max_seconds=self.settings.max_audio_seconds,
        )
        audio_path = self.repository.upload_audio(
            str(job.job_id),
            metadata.filename,
            data,
            metadata.mime_type,
        )
        return self.repository.update_job(
            str(job.job_id),
            {
                "audio_path": audio_path,
                "filename": metadata.filename,
                "mime_type": metadata.mime_type,
                "size_bytes": metadata.size_bytes,
                "duration_seconds": metadata.duration_seconds,
            },
        )


def error_info_from_exception(exc: Exception) -> ErrorInfo:
    return ErrorInfo(
        code=getattr(exc, "code", exc.__class__.__name__),
        message=getattr(exc, "message", str(exc)),
        retryable=bool(getattr(exc, "retryable", False)),
        provider_status_code=getattr(exc, "status_code", None),
    )


def enqueue_transcription_task(job_id: str) -> None:
    from app.workers.tasks import process_transcription_job

    process_transcription_job.delay(job_id)
