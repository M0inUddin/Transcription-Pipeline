from app.core.config import get_settings
from app.core.errors import JobNotFoundError, PipelineError
from app.services import ModelServicesRouter, TranscriptionProcessor
from app.services.transcription import error_info_from_exception
from app.storage import SupabaseStorageRepository
from app.workers.celery_app import celery_app


@celery_app.task(bind=True, name="app.workers.tasks.process_transcription_job")
def process_transcription_job(self, job_id: str) -> dict:
    settings = get_settings()
    repository = None

    try:
        repository = SupabaseStorageRepository(settings)
        provider = ModelServicesRouter(settings).transcription_provider()
        processor = TranscriptionProcessor(repository, provider, settings=settings)
        job = processor.process_job(job_id)
        return {"job_id": str(job.job_id), "status": job.status}
    except JobNotFoundError as exc:
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    except PipelineError as exc:
        if (
            getattr(exc, "retryable", False)
            and self.request.retries < settings.worker_max_retries
        ):
            retry_count = self.request.retries + 1
            _safe_update(
                repository,
                job_id,
                status="retrying",
                retry_count=retry_count,
                error=error_info_from_exception(exc),
            )
            raise self.retry(
                exc=exc,
                countdown=_retry_countdown(
                    settings.worker_retry_backoff_seconds, self.request.retries
                ),
                max_retries=settings.worker_max_retries,
            )

        _safe_update(
            repository, job_id, status="failed", error=error_info_from_exception(exc)
        )
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    except Exception as exc:
        if self.request.retries < settings.worker_max_retries:
            retry_count = self.request.retries + 1
            _safe_update(
                repository,
                job_id,
                status="retrying",
                retry_count=retry_count,
                error={
                    "code": "unhandled_exception",
                    "message": str(exc),
                    "retryable": True,
                },
            )
            raise self.retry(
                exc=exc,
                countdown=_retry_countdown(
                    settings.worker_retry_backoff_seconds, self.request.retries
                ),
                max_retries=settings.worker_max_retries,
            )

        _safe_update(
            repository,
            job_id,
            status="failed",
            error={
                "code": "unhandled_exception",
                "message": str(exc),
                "retryable": False,
            },
        )
        return {"job_id": job_id, "status": "failed", "error": str(exc)}


def _retry_countdown(base_seconds: int, retries_so_far: int) -> int:
    return min(base_seconds * (2**retries_so_far), 300)


def _safe_update(repository, job_id: str, **values) -> None:
    if repository is None:
        return
    try:
        repository.update_job(job_id, values)
    except PipelineError:
        return
