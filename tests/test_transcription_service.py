import base64

import pytest

from app.core.errors import QueueingError
from app.core.config import Settings
from app.schemas import InputSource, JobStatus
from app.services import TranscriptionProcessor, TranscriptionService
from tests.fakes import FakeProvider, FakeRepository


def test_create_file_job_uploads_audio_and_enqueues() -> None:
    repository = FakeRepository()
    enqueued: list[str] = []
    service = TranscriptionService(
        repository,
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
        task_sender=enqueued.append,
    )

    response = service.create_job(file_bytes=b"ID3audio", filename="sample.mp3", mime_type="audio/mpeg")

    job = repository.get_job(str(response.job_id))
    assert response.status == JobStatus.queued
    assert enqueued == [str(response.job_id)]
    assert job is not None
    assert job.source_type == InputSource.file
    assert job.audio_path in repository.audio


def test_create_base64_job_normalizes_to_audio_file() -> None:
    repository = FakeRepository()
    service = TranscriptionService(
        repository,
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
        task_sender=lambda _: None,
    )
    encoded = base64.b64encode(b"ID3audio").decode("ascii")

    response = service.create_job(audio_base64=f"data:audio/mpeg;base64,{encoded}")
    job = repository.get_job(str(response.job_id))

    assert job is not None
    assert job.source_type == InputSource.base64
    assert job.filename == "audio.mp3"


def test_processor_completes_job_and_persists_transcript() -> None:
    repository = FakeRepository()
    service = TranscriptionService(
        repository,
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
        task_sender=lambda _: None,
    )
    response = service.create_job(file_bytes=b"ID3audio", filename="sample.mp3", mime_type="audio/mpeg")
    processor = TranscriptionProcessor(
        repository,
        FakeProvider("completed transcript"),
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
    )

    job = processor.process_job(response.job_id)

    assert job.status == JobStatus.completed
    assert job.text == "completed transcript"
    assert job.words[0].word == "hello"
    assert job.segments[0].speaker == 0
    assert job.detected_language == "en"
    assert job.language_confidence == 0.98
    assert job.transcript_path in repository.transcripts
    assert repository.transcripts[job.transcript_path]["segments"][0]["start"] == 0.0
    assert repository.transcripts[job.transcript_path]["words"][0]["speaker"] == 0
    assert repository.transcripts[job.transcript_path]["detected_language"] == "en"


def test_processor_skips_already_completed_job() -> None:
    repository = FakeRepository()
    service = TranscriptionService(
        repository,
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
        task_sender=lambda _: None,
    )
    response = service.create_job(file_bytes=b"ID3audio", filename="sample.mp3", mime_type="audio/mpeg")
    processor = TranscriptionProcessor(
        repository,
        FakeProvider("first"),
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
    )
    completed = processor.process_job(response.job_id)

    second_provider = FakeProvider("second")
    processor = TranscriptionProcessor(
        repository,
        second_provider,
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
    )
    skipped = processor.process_job(completed.job_id)

    assert skipped.text == "first"
    assert second_provider.calls == []


def test_create_job_marks_job_failed_when_enqueue_fails() -> None:
    repository = FakeRepository()

    def failing_sender(_: str) -> None:
        raise RuntimeError("redis unavailable")

    service = TranscriptionService(
        repository,
        settings=Settings(max_audio_bytes=100, max_audio_seconds=1800),
        task_sender=failing_sender,
    )

    with pytest.raises(QueueingError):
        service.create_job(file_bytes=b"ID3audio", filename="sample.mp3", mime_type="audio/mpeg")

    job = next(iter(repository.jobs.values()))
    assert job.status == JobStatus.failed
    assert job.error is not None
    assert job.error.code == "queueing_error"
    assert job.error.retryable is True
