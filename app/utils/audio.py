import os
import re
import base64
import binascii
import ipaddress
import mimetypes
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.errors import AudioValidationError, TransientProcessingError
from app.schemas import AudioMetadata

SUPPORTED_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp2",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}

SUPPORTED_MIME_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
    "audio/wave",
    "audio/webm",
    "video/mp4",
    "video/webm",
    "application/ogg",
}

MIME_TO_EXTENSION = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/ogg": ".ogg",
}

DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[-\w.]+/[-\w.+]+);base64,(?P<data>.*)$", re.DOTALL
)
MAX_REMOTE_REDIRECTS = 5


def validate_single_input(
    *, has_file: bool, audio_url: str | None, audio_base64: str | None
) -> None:
    provided = [has_file, bool(audio_url), bool(audio_base64)]
    if sum(provided) != 1:
        raise AudioValidationError(
            "Provide exactly one input: multipart file, audio_url, or audio_base64."
        )


def decode_base64_audio(audio_base64: str) -> tuple[bytes, str | None]:
    value = audio_base64.strip()
    mime_type: str | None = None
    match = DATA_URI_RE.match(value)
    if match:
        mime_type = clean_mime_type(match.group("mime"))
        value = match.group("data")

    try:
        return base64.b64decode(value, validate=True), mime_type
    except (binascii.Error, ValueError) as exc:
        raise AudioValidationError("audio_base64 is not valid base64 data.") from exc


def validate_remote_url(audio_url: str, *, resolve_host: bool = False) -> str:
    parsed = urlparse(audio_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AudioValidationError("audio_url must be an absolute http or https URL.")
    if parsed.username or parsed.password:
        raise AudioValidationError("audio_url must not include credentials.")
    hostname = parsed.hostname
    if not hostname:
        raise AudioValidationError("audio_url must include a hostname.")
    validate_public_hostname(hostname, resolve_host=resolve_host)
    return audio_url


def download_remote_audio(
    audio_url: str, *, max_bytes: int, timeout_seconds: int
) -> tuple[bytes, str, str | None]:
    current_url = validate_remote_url(audio_url, resolve_host=True)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
            for _ in range(MAX_REMOTE_REDIRECTS + 1):
                validate_remote_url(current_url, resolve_host=True)
                with client.stream(
                    "GET", current_url, follow_redirects=False
                ) as response:
                    if response.is_redirect:
                        next_request = response.next_request
                        if not next_request:
                            raise AudioValidationError(
                                "Remote audio redirect is missing a Location header."
                            )
                        current_url = validate_remote_url(
                            str(next_request.url), resolve_host=True
                        )
                        continue

                    if (
                        response.status_code in {408, 429}
                        or 500 <= response.status_code <= 599
                    ):
                        raise TransientProcessingError(
                            f"Remote audio download returned retryable status {response.status_code}.",
                            status_code=response.status_code,
                        )
                    if response.status_code >= 400:
                        raise AudioValidationError(
                            f"Remote audio download failed with status {response.status_code}.",
                            status_code=response.status_code,
                        )

                    content_length = _int_or_none(
                        response.headers.get("content-length")
                    )
                    if content_length and content_length > max_bytes:
                        raise AudioValidationError(
                            f"Remote audio exceeds max size of {max_bytes} bytes."
                        )

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise AudioValidationError(
                                f"Remote audio exceeds max size of {max_bytes} bytes."
                            )
                        chunks.append(chunk)

                    filename = filename_from_url(current_url)
                    mime_type = clean_mime_type(response.headers.get("content-type"))
                    return b"".join(chunks), filename, mime_type

            raise AudioValidationError("Remote audio exceeded maximum redirect depth.")
    except httpx.TimeoutException as exc:
        raise TransientProcessingError(
            "Timed out while downloading remote audio."
        ) from exc
    except httpx.TransportError as exc:
        raise TransientProcessingError(
            "Network error while downloading remote audio."
        ) from exc


def validate_public_hostname(hostname: str, *, resolve_host: bool) -> None:
    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        if _is_local_hostname(hostname):
            raise AudioValidationError("audio_url host must be a public internet host.")
        if resolve_host:
            for address in resolve_hostname(hostname):
                validate_public_ip(address)
        return

    validate_public_ip(ip)


def resolve_hostname(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise TransientProcessingError(
            f"Could not resolve remote audio host: {hostname}."
        ) from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for result in results:
        address = result[4][0]
        try:
            addresses.append(ipaddress.ip_address(address))
        except ValueError:
            continue
    if not addresses:
        raise TransientProcessingError(
            f"Could not resolve remote audio host: {hostname}."
        )
    return addresses


def validate_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global:
        raise AudioValidationError(
            "audio_url host must resolve to a public internet address."
        )


def _is_local_hostname(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    return normalized in {"localhost"} or normalized.endswith(".localhost")


def validate_audio_bytes(
    data: bytes,
    *,
    filename: str | None,
    declared_mime_type: str | None,
    max_bytes: int,
    max_seconds: int,
) -> AudioMetadata:
    if not data:
        raise AudioValidationError("Audio payload is empty.")
    if len(data) > max_bytes:
        raise AudioValidationError(
            f"Audio payload exceeds max size of {max_bytes} bytes."
        )

    cleaned_filename = safe_filename(filename)
    mime_type = infer_mime_type(data, cleaned_filename, declared_mime_type)
    suffix = suffix_for(cleaned_filename, mime_type)

    if not is_supported_audio(suffix, mime_type):
        raise AudioValidationError(
            "Unsupported audio format. Use MP3, WAV, MP4, M4A, FLAC, Ogg, Opus, or WebM."
        )

    if not cleaned_filename:
        cleaned_filename = f"audio{suffix or MIME_TO_EXTENSION.get(mime_type, '.bin')}"
    elif suffix and not Path(cleaned_filename).suffix:
        cleaned_filename = f"{cleaned_filename}{suffix}"

    duration_seconds = probe_audio_duration_seconds(data, suffix)
    if duration_seconds is not None and duration_seconds > max_seconds:
        raise AudioValidationError(
            f"Audio duration exceeds max length of {max_seconds} seconds."
        )

    return AudioMetadata(
        filename=cleaned_filename,
        mime_type=mime_type,
        size_bytes=len(data),
        duration_seconds=duration_seconds,
    )


def clean_mime_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower() or None


def safe_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    name = Path(filename).name.strip().replace("\\", "_").replace("/", "_")
    return name or None


def filename_from_url(audio_url: str) -> str:
    path = urlparse(audio_url).path
    name = safe_filename(Path(path).name)
    return name or "remote-audio"


def infer_mime_type(
    data: bytes, filename: str | None, declared_mime_type: str | None
) -> str:
    detected = detect_mime_from_signature(data)
    declared = clean_mime_type(declared_mime_type)
    guessed = clean_mime_type(mimetypes.guess_type(filename or "")[0])

    if detected:
        return detected
    if declared and declared != "application/octet-stream":
        return declared
    if guessed:
        return guessed
    return declared or "application/octet-stream"


def detect_mime_from_signature(data: bytes) -> str | None:
    header = data[:64]
    if header.startswith(b"ID3") or header[:2] in {
        b"\xff\xfb",
        b"\xff\xf3",
        b"\xff\xf2",
    }:
        return "audio/mpeg"
    if header.startswith(b"RIFF") and b"WAVE" in header[:16]:
        return "audio/wav"
    if header.startswith(b"fLaC"):
        return "audio/flac"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    if len(header) > 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


def suffix_for(filename: str | None, mime_type: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    if mime_type:
        return MIME_TO_EXTENSION.get(mime_type, "")
    return ""


def is_supported_audio(suffix: str, mime_type: str | None) -> bool:
    if suffix in SUPPORTED_EXTENSIONS:
        return True
    return bool(mime_type and mime_type in SUPPORTED_MIME_TYPES)


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def probe_audio_duration_seconds(data: bytes, suffix: str) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix or ".audio"
        ) as handle:
            handle.write(data)
            tmp_path = handle.name

        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        return float(output) if output else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
