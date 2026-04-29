from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        deepgram_configured=bool(settings.deepgram_api_key),
        supabase_configured=bool(
            settings.supabase_url and settings.supabase_service_role_key
        ),
        redis_url_configured=bool(settings.broker_url),
        storage_audio_bucket=settings.audio_bucket,
        storage_transcript_bucket=settings.transcript_bucket,
    )
