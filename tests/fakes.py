from datetime import UTC, datetime

from app.schemas import ProviderTranscript, TranscriptSegment, TranscriptWord, TranscriptionJob


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, TranscriptionJob] = {}
        self.audio: dict[str, bytes] = {}
        self.transcripts: dict[str, dict] = {}

    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        self.jobs[str(job.job_id)] = job
        return job

    def get_job(self, job_id: str) -> TranscriptionJob | None:
        return self.jobs.get(str(job_id))

    def update_job(self, job_id: str, values: dict) -> TranscriptionJob:
        job = self.jobs[str(job_id)]
        payload = job.model_dump()
        payload.update(values)
        payload.setdefault("updated_at", datetime.now(UTC))
        updated = TranscriptionJob.model_validate(payload)
        self.jobs[str(job_id)] = updated
        return updated

    def upload_audio(self, job_id: str, filename: str, data: bytes, mime_type: str) -> str:
        path = f"{job_id}/{filename}"
        self.audio[path] = data
        return path

    def upload_transcript(self, job_id: str, transcript: dict) -> str:
        path = f"{job_id}/transcript.json"
        self.transcripts[path] = transcript
        return path

    def download_audio(self, path: str) -> bytes:
        return self.audio[path]


class FakeProvider:
    def __init__(self, text: str = "hello world") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    def transcribe_bytes(self, audio: bytes, mime_type: str) -> ProviderTranscript:
        self.calls.append((audio, mime_type))
        return ProviderTranscript(
            provider_request_id="dg-request-1",
            text=self.text,
            segments=[TranscriptSegment(start=0.0, end=1.2, text=self.text, speaker=0)],
            words=[
                TranscriptWord(
                    word="hello",
                    punctuated_word="Hello",
                    start=0.0,
                    end=0.5,
                    confidence=0.99,
                    speaker=0,
                    speaker_confidence=0.95,
                )
            ],
            detected_language="en",
            language_confidence=0.98,
            raw_response={"metadata": {"request_id": "dg-request-1"}},
        )
