from app.services import TranscriptionService
from app.storage import SupabaseStorageRepository


def get_repository() -> SupabaseStorageRepository:
    return SupabaseStorageRepository()


def get_transcription_service() -> TranscriptionService:
    return TranscriptionService(get_repository())

