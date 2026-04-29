from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Transcription Pipeline"
    environment: str = "local"

    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_api_url: str = "https://api.deepgram.com/v1/listen"
    deepgram_model: str = "nova-3"
    deepgram_timeout_seconds: int = 620

    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_service_role_key: str | None = Field(
        default=None, alias="SUPABASE_SERVICE_ROLE_KEY"
    )
    supabase_storage_bucket: str | None = Field(
        default=None, alias="SUPABASE_STORAGE_BUCKET"
    )
    supabase_audio_bucket: str | None = Field(
        default=None, alias="SUPABASE_AUDIO_BUCKET"
    )
    supabase_transcript_bucket: str | None = Field(
        default=None, alias="SUPABASE_TRANSCRIPT_BUCKET"
    )
    supabase_jobs_table: str = Field(
        default="transcription_jobs", alias="SUPABASE_JOBS_TABLE"
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(
        default=None, alias="CELERY_RESULT_BACKEND"
    )
    worker_max_retries: int = Field(default=3, alias="WORKER_MAX_RETRIES")
    worker_retry_backoff_seconds: int = Field(
        default=15, alias="WORKER_RETRY_BACKOFF_SECONDS"
    )

    max_audio_bytes: int = Field(default=25 * 1024 * 1024, alias="MAX_AUDIO_BYTES")
    max_audio_seconds: int = Field(default=30 * 60, alias="MAX_AUDIO_SECONDS")
    remote_download_timeout_seconds: int = Field(
        default=60, alias="REMOTE_DOWNLOAD_TIMEOUT_SECONDS"
    )

    @property
    def audio_bucket(self) -> str:
        return (
            self.supabase_audio_bucket
            or self.supabase_storage_bucket
            or "transcription-audio"
        )

    @property
    def transcript_bucket(self) -> str:
        return (
            self.supabase_transcript_bucket
            or self.supabase_storage_bucket
            or "transcription-results"
        )

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend_url(self) -> str:
        return self.celery_result_backend or self.redis_url

    def require_deepgram(self) -> None:
        if not self.deepgram_api_key:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is required for transcription processing."
            )

    def require_supabase(self) -> None:
        missing = [
            name
            for name, value in {
                "SUPABASE_URL": self.supabase_url,
                "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Missing required Supabase configuration: {', '.join(missing)}."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
