from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"


class ProviderName(StrEnum):
    deepgram = "deepgram"


class InputSource(StrEnum):
    file = "file"
    remote_url = "remote_url"
    base64 = "base64"


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def end_must_not_precede_start(self) -> "TranscriptSegment":
        if self.end < self.start:
            raise ValueError("segment end must be greater than or equal to start")
        return self


class TranscriptWord(BaseModel):
    word: str
    punctuated_word: str | None = None
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    speaker: int | None = Field(default=None, ge=0)
    speaker_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def end_must_not_precede_start(self) -> "TranscriptWord":
        if self.end < self.start:
            raise ValueError("word end must be greater than or equal to start")
        return self


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False
    provider_status_code: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AudioMetadata(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)


class ProviderTranscript(BaseModel):
    provider: ProviderName = ProviderName.deepgram
    provider_request_id: str | None = None
    text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    words: list[TranscriptWord] = Field(default_factory=list)
    detected_language: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    raw_response: dict[str, Any]


class QueuedTranscriptionResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    provider: ProviderName = ProviderName.deepgram


class TranscriptionResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    provider: ProviderName = ProviderName.deepgram
    text: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    words: list[TranscriptWord] = Field(default_factory=list)
    detected_language: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    error: ErrorInfo | None = None
    retry_count: int = 0
    provider_request_id: str | None = None
    audio_path: str | None = None
    transcript_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class TranscriptionJob(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: UUID = Field(default_factory=uuid4)
    status: JobStatus = JobStatus.queued
    provider: ProviderName = ProviderName.deepgram
    source_type: InputSource
    source_url: HttpUrl | None = None
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    audio_path: str | None = None
    transcript_path: str | None = None
    text: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    words: list[TranscriptWord] = Field(default_factory=list)
    detected_language: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    error: ErrorInfo | None = None
    retry_count: int = 0
    provider_request_id: str | None = None
    raw_provider_response: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @field_validator("source_url", mode="before")
    @classmethod
    def empty_url_to_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    def to_response(self) -> TranscriptionResponse:
        return TranscriptionResponse(
            job_id=self.job_id,
            status=JobStatus(self.status),
            provider=ProviderName(self.provider),
            text=self.text,
            segments=self.segments,
            words=self.words,
            detected_language=self.detected_language,
            language_confidence=self.language_confidence,
            error=self.error,
            retry_count=self.retry_count,
            provider_request_id=self.provider_request_id,
            audio_path=self.audio_path,
            transcript_path=self.transcript_path,
            created_at=self.created_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
        )


class HealthResponse(BaseModel):
    status: str
    deepgram_configured: bool
    supabase_configured: bool
    redis_url_configured: bool
    storage_audio_bucket: str
    storage_transcript_bucket: str
