from datetime import UTC, datetime
from enum import Enum
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError, JobNotFoundError, StorageError
from app.schemas import TranscriptionJob
from app.utils.audio import safe_filename


class SupabaseStorageRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        try:
            self.settings.require_supabase()
        except RuntimeError as exc:
            raise ConfigurationError(str(exc)) from exc

        try:
            from supabase import create_client
        except ImportError as exc:
            raise ConfigurationError(
                "Install the supabase package to use Supabase storage."
            ) from exc

        self.client = create_client(
            self.settings.supabase_url,
            self.settings.supabase_service_role_key,
        )

    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        try:
            response = (
                self.client.table(self.settings.supabase_jobs_table)
                .insert(_jsonable(job))
                .execute()
            )
            rows = response.data or []
            return TranscriptionJob.model_validate(rows[0] if rows else _jsonable(job))
        except Exception as exc:
            raise StorageError(f"Failed to create transcription job: {exc}") from exc

    def get_job(self, job_id: str) -> TranscriptionJob | None:
        try:
            response = (
                self.client.table(self.settings.supabase_jobs_table)
                .select("*")
                .eq("job_id", job_id)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            if not rows:
                return None
            return TranscriptionJob.model_validate(rows[0])
        except Exception as exc:
            raise StorageError(
                f"Failed to read transcription job {job_id}: {exc}"
            ) from exc

    def update_job(self, job_id: str, values: dict) -> TranscriptionJob:
        payload = _jsonable(values)
        payload.setdefault("updated_at", datetime.now(UTC).isoformat())
        try:
            response = (
                self.client.table(self.settings.supabase_jobs_table)
                .update(payload)
                .eq("job_id", job_id)
                .execute()
            )
            rows = response.data or []
            if not rows:
                raise JobNotFoundError(f"Transcription job {job_id} was not found.")
            return TranscriptionJob.model_validate(rows[0])
        except JobNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(
                f"Failed to update transcription job {job_id}: {exc}"
            ) from exc

    def upload_audio(
        self, job_id: str, filename: str, data: bytes, mime_type: str
    ) -> str:
        path = f"{job_id}/{safe_filename(filename) or 'audio'}"
        return self._upload_bytes(self.settings.audio_bucket, path, data, mime_type)

    def upload_transcript(self, job_id: str, transcript: dict) -> str:
        path = f"{job_id}/transcript.json"
        data = json.dumps(transcript, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return self._upload_bytes(
            self.settings.transcript_bucket, path, data, "application/json"
        )

    def download_audio(self, path: str) -> bytes:
        try:
            return self.client.storage.from_(self.settings.audio_bucket).download(path)
        except Exception as exc:
            raise StorageError(
                f"Failed to download audio object {path}: {exc}"
            ) from exc

    def _upload_bytes(self, bucket: str, path: str, data: bytes, mime_type: str) -> str:
        try:
            self.client.storage.from_(bucket).upload(
                path=path,
                file=data,
                file_options={
                    "cache-control": "3600",
                    "content-type": mime_type,
                    "upsert": "true",
                },
            )
            return path
        except Exception as exc:
            raise StorageError(
                f"Failed to upload object {path} to bucket {bucket}: {exc}"
            ) from exc


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
