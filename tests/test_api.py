from fastapi.testclient import TestClient

from app.core.config import Settings
from app.dependencies import get_transcription_service
from app.main import create_app
from app.schemas import JobStatus, TranscriptSegment, TranscriptWord, TranscriptionJob
from app.services import TranscriptionService
from tests.fakes import FakeRepository


def build_client(repository: FakeRepository, enqueued: list[str]) -> TestClient:
    app = create_app()

    def override_service() -> TranscriptionService:
        return TranscriptionService(
            repository,
            settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
            task_sender=enqueued.append,
        )

    app.dependency_overrides[get_transcription_service] = override_service
    return TestClient(app)


def test_health_reports_configuration_shape() -> None:
    client = build_client(FakeRepository(), [])

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "deepgram_configured" in response.json()


def test_post_transcriptions_accepts_multipart_file() -> None:
    repository = FakeRepository()
    enqueued: list[str] = []
    client = build_client(repository, enqueued)

    response = client.post(
        "/transcriptions",
        files={"file": ("sample.mp3", b"ID3audio", "audio/mpeg")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert enqueued == [body["job_id"]]


def test_post_transcriptions_accepts_json_url() -> None:
    repository = FakeRepository()
    enqueued: list[str] = []
    client = build_client(repository, enqueued)

    response = client.post("/transcriptions", json={"audio_url": "https://example.com/audio.mp3"})

    assert response.status_code == 202
    body = response.json()
    job = repository.get_job(body["job_id"])
    assert job is not None
    assert str(job.source_url) == "https://example.com/audio.mp3"


def test_post_transcriptions_rejects_non_object_json() -> None:
    client = build_client(FakeRepository(), [])

    response = client.post("/transcriptions", json=[])

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "audio_validation_error"


def test_get_transcription_returns_stored_job() -> None:
    repository = FakeRepository()
    job = repository.create_job(
        TranscriptionJob(
            status=JobStatus.completed,
            source_type="file",
            filename="sample.mp3",
            mime_type="audio/mpeg",
            text="done",
            segments=[TranscriptSegment(start=0.0, end=1.0, text="done", speaker=0)],
            words=[TranscriptWord(word="done", start=0.0, end=1.0, speaker=0)],
            detected_language="en",
            language_confidence=0.99,
        )
    )
    client = build_client(repository, [])

    response = client.get(f"/transcriptions/{job.job_id}")

    assert response.status_code == 200
    assert response.json()["text"] == "done"
    assert response.json()["segments"][0]["speaker"] == 0
    assert response.json()["words"][0]["word"] == "done"
    assert response.json()["detected_language"] == "en"
