from app.core.config import Settings
import app.providers.deepgram as deepgram
from app.providers.deepgram import DeepgramProvider, parse_deepgram_response


def test_deepgram_provider_enables_required_transcription_options(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "metadata": {"request_id": "abc"},
                "results": {"channels": [{"alternatives": [{"transcript": "hello"}]}]},
            }

    class FakeClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, *_: object, **kwargs: object) -> FakeResponse:
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(deepgram.httpx, "Client", FakeClient)

    provider = DeepgramProvider(Settings(deepgram_api_key="test-key"))
    provider.transcribe_bytes(b"ID3audio", "audio/mpeg")

    assert captured["params"]["utterances"] == "true"
    assert captured["params"]["diarize"] == "true"
    assert captured["params"]["detect_language"] == "true"


def test_parse_deepgram_response_uses_utterances_for_segments() -> None:
    transcript = parse_deepgram_response(
        {
            "metadata": {"request_id": "abc", "duration": 2.1},
            "results": {
                "channels": [
                    {
                        "detected_language": "en",
                        "language_confidence": 0.98,
                        "alternatives": [
                            {
                                "transcript": "Hello there.",
                                "words": [
                                    {
                                        "word": "hello",
                                        "punctuated_word": "Hello",
                                        "start": 0.0,
                                        "end": 0.5,
                                        "confidence": 0.99,
                                        "speaker": 0,
                                        "speaker_confidence": 0.95,
                                    },
                                    {
                                        "word": "there",
                                        "punctuated_word": "there.",
                                        "start": 0.6,
                                        "end": 1.0,
                                        "confidence": 0.97,
                                        "speaker": 0,
                                        "speaker_confidence": 0.94,
                                    },
                                ],
                            }
                        ]
                    }
                ],
                "utterances": [
                    {
                        "start": 0,
                        "end": 2.1,
                        "transcript": "Hello there.",
                        "speaker": 0,
                    }
                ],
            },
        }
    )

    assert transcript.provider_request_id == "abc"
    assert transcript.text == "Hello there."
    assert transcript.segments[0].start == 0
    assert transcript.segments[0].end == 2.1
    assert transcript.segments[0].text == "Hello there."
    assert transcript.segments[0].speaker == 0
    assert transcript.words[0].word == "hello"
    assert transcript.words[0].punctuated_word == "Hello"
    assert transcript.words[0].speaker == 0
    assert transcript.detected_language == "en"
    assert transcript.language_confidence == 0.98


def test_parse_deepgram_response_falls_back_to_word_span() -> None:
    transcript = parse_deepgram_response(
        {
            "metadata": {"request_id": "abc"},
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": "hello world",
                                "words": [
                                    {"word": "hello", "start": 0.1, "end": 0.4, "speaker": 1},
                                    {"word": "world", "start": 0.5, "end": 0.9, "speaker": 1},
                                ],
                            }
                        ]
                    }
                ]
            },
        }
    )

    assert len(transcript.segments) == 1
    assert transcript.segments[0].start == 0.1
    assert transcript.segments[0].end == 0.9
    assert transcript.segments[0].speaker == 1
    assert len(transcript.words) == 2
