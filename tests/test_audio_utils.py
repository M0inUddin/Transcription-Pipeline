import base64
import ipaddress

import httpx
import pytest

from app.core.errors import AudioValidationError
from app.utils import audio
from app.utils.audio import decode_base64_audio, validate_audio_bytes, validate_remote_url, validate_single_input


def test_validate_single_input_requires_exactly_one_source() -> None:
    validate_single_input(has_file=True, audio_url=None, audio_base64=None)

    with pytest.raises(AudioValidationError):
        validate_single_input(has_file=True, audio_url="https://example.com/a.mp3", audio_base64=None)

    with pytest.raises(AudioValidationError):
        validate_single_input(has_file=False, audio_url=None, audio_base64=None)


def test_decode_base64_audio_supports_data_uri() -> None:
    encoded = base64.b64encode(b"ID3audio").decode("ascii")

    data, mime_type = decode_base64_audio(f"data:audio/mpeg;base64,{encoded}")

    assert data == b"ID3audio"
    assert mime_type == "audio/mpeg"


def test_validate_audio_bytes_accepts_common_deepgram_format() -> None:
    metadata = validate_audio_bytes(
        b"ID3audio",
        filename="sample.mp3",
        declared_mime_type="audio/mpeg",
        max_bytes=100,
        max_seconds=1800,
    )

    assert metadata.filename == "sample.mp3"
    assert metadata.mime_type == "audio/mpeg"
    assert metadata.size_bytes == 8


def test_validate_audio_bytes_rejects_oversized_payload() -> None:
    with pytest.raises(AudioValidationError):
        validate_audio_bytes(
            b"ID3audio",
            filename="sample.mp3",
            declared_mime_type="audio/mpeg",
            max_bytes=4,
            max_seconds=1800,
        )


def test_validate_remote_url_rejects_internal_literal_hosts() -> None:
    for url in [
        "http://127.0.0.1/audio.mp3",
        "http://localhost/audio.mp3",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.2/audio.mp3",
        "http://[::1]/audio.mp3",
    ]:
        with pytest.raises(AudioValidationError):
            validate_remote_url(url)


def test_validate_remote_url_rejects_domains_that_resolve_to_private_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio, "resolve_hostname", lambda _: [ipaddress.ip_address("10.0.0.1")])

    with pytest.raises(AudioValidationError):
        validate_remote_url("https://example.com/audio.mp3", resolve_host=True)


def test_download_remote_audio_validates_redirect_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    class RedirectResponse:
        status_code = 302
        headers = {}
        is_redirect = True
        next_request = httpx.Request("GET", "http://127.0.0.1/internal.mp3")

        def __enter__(self) -> "RedirectResponse":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class FakeClient:
        def __init__(self, *_: object, **__: object) -> None:
            self.calls = 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def stream(self, *_: object, **__: object) -> RedirectResponse:
            self.calls += 1
            return RedirectResponse()

    monkeypatch.setattr(audio, "resolve_hostname", lambda _: [ipaddress.ip_address("93.184.216.34")])
    monkeypatch.setattr(audio.httpx, "Client", FakeClient)

    with pytest.raises(AudioValidationError):
        audio.download_remote_audio("https://example.com/audio.mp3", max_bytes=100, timeout_seconds=5)
