from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import (
    ConfigurationError,
    PermanentProviderError,
    TransientProviderError,
)
from app.schemas import ProviderTranscript, TranscriptSegment, TranscriptWord


class DeepgramProvider:
    provider_name = "deepgram"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        try:
            self.settings.require_deepgram()
        except RuntimeError as exc:
            raise ConfigurationError(str(exc)) from exc

    def transcribe_bytes(self, audio: bytes, mime_type: str) -> ProviderTranscript:
        headers = self._headers(content_type=mime_type)
        response_json = self._post(headers=headers, content=audio)
        return parse_deepgram_response(response_json)

    def transcribe_url(self, audio_url: str) -> ProviderTranscript:
        headers = self._headers(content_type="application/json")
        response_json = self._post(headers=headers, json={"url": audio_url})
        return parse_deepgram_response(response_json)

    def _post(
        self,
        *,
        headers: dict[str, str],
        content: bytes | None = None,
        json: dict | None = None,
    ) -> dict:
        params = {
            "model": self.settings.deepgram_model,
            "smart_format": "true",
            "utterances": "true",
            "diarize": "true",
            "detect_language": "true",
        }
        try:
            with httpx.Client(timeout=self.settings.deepgram_timeout_seconds) as client:
                response = client.post(
                    self.settings.deepgram_api_url,
                    params=params,
                    headers=headers,
                    content=content,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise TransientProviderError("Deepgram request timed out.") from exc
        except httpx.TransportError as exc:
            raise TransientProviderError(
                "Network error while contacting Deepgram."
            ) from exc

        if response.status_code in {408, 429} or 500 <= response.status_code <= 599:
            raise TransientProviderError(
                _provider_error_message(response),
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise PermanentProviderError(
                _provider_error_message(response),
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise TransientProviderError(
                "Deepgram returned a non-JSON response."
            ) from exc

    def _headers(self, *, content_type: str) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.settings.deepgram_api_key}",
            "Content-Type": content_type,
        }


def parse_deepgram_response(response: dict[str, Any]) -> ProviderTranscript:
    metadata = response.get("metadata") or {}
    results = response.get("results") or {}
    channel = _first_channel(results)
    alternative = _first_alternative(channel)
    text = str(alternative.get("transcript") or "").strip()
    words = _words_from_alternative(alternative)
    segments = _segments_from_utterances(results) or _segments_from_paragraphs(
        alternative
    )
    segments = segments or _segment_from_words(alternative, text)

    if not segments and text:
        duration = _float_or_none(metadata.get("duration")) or 0.0
        segments = [TranscriptSegment(start=0.0, end=duration, text=text)]

    return ProviderTranscript(
        provider_request_id=metadata.get("request_id"),
        text=text,
        segments=segments,
        words=words,
        detected_language=_detected_language(channel, alternative, metadata),
        language_confidence=_language_confidence(channel, alternative, metadata),
        raw_response=response,
    )


def _first_channel(results: dict[str, Any]) -> dict[str, Any]:
    channels = results.get("channels") or []
    if not channels:
        return {}
    return channels[0] or {}


def _first_alternative(channel: dict[str, Any]) -> dict[str, Any]:
    alternatives = channel.get("alternatives") or []
    if not alternatives:
        return {}
    return alternatives[0] or {}


def _segments_from_utterances(results: dict[str, Any]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for utterance in results.get("utterances") or []:
        segment = _segment_from_mapping(utterance, text_key="transcript")
        if segment:
            segments.append(segment)
    return segments


def _segments_from_paragraphs(alternative: dict[str, Any]) -> list[TranscriptSegment]:
    paragraphs = (alternative.get("paragraphs") or {}).get("paragraphs") or []
    segments: list[TranscriptSegment] = []
    for paragraph in paragraphs:
        sentences = paragraph.get("sentences") or []
        if sentences:
            for sentence in sentences:
                segment = _segment_from_mapping(sentence, text_key="text")
                if segment:
                    segments.append(segment)
        else:
            segment = _segment_from_mapping(paragraph, text_key="text")
            if segment:
                segments.append(segment)
    return segments


def _segment_from_words(
    alternative: dict[str, Any], text: str
) -> list[TranscriptSegment]:
    words = alternative.get("words") or []
    if not words or not text:
        return []
    start = _float_or_none(words[0].get("start"))
    end = _float_or_none(words[-1].get("end"))
    if start is None or end is None:
        return []
    return [
        TranscriptSegment(
            start=start, end=end, text=text, speaker=_speaker_if_consistent(words)
        )
    ]


def _segment_from_mapping(
    value: dict[str, Any], *, text_key: str
) -> TranscriptSegment | None:
    start = _float_or_none(value.get("start"))
    end = _float_or_none(value.get("end"))
    text = str(value.get(text_key) or "").strip()
    if start is None or end is None or not text:
        return None
    return TranscriptSegment(
        start=start, end=end, text=text, speaker=_int_or_none(value.get("speaker"))
    )


def _words_from_alternative(alternative: dict[str, Any]) -> list[TranscriptWord]:
    parsed: list[TranscriptWord] = []
    for item in alternative.get("words") or []:
        start = _float_or_none(item.get("start"))
        end = _float_or_none(item.get("end"))
        word = str(item.get("word") or "").strip()
        if start is None or end is None or not word:
            continue
        parsed.append(
            TranscriptWord(
                word=word,
                punctuated_word=_optional_str(item.get("punctuated_word")),
                start=start,
                end=end,
                confidence=_float_or_none(item.get("confidence")),
                speaker=_int_or_none(item.get("speaker")),
                speaker_confidence=_float_or_none(item.get("speaker_confidence")),
            )
        )
    return parsed


def _detected_language(
    channel: dict[str, Any],
    alternative: dict[str, Any],
    metadata: dict[str, Any],
) -> str | None:
    for value in (
        channel.get("detected_language"),
        alternative.get("detected_language"),
        metadata.get("detected_language"),
        channel.get("language"),
        alternative.get("language"),
    ):
        text = _optional_str(value)
        if text:
            return text
    return None


def _language_confidence(
    channel: dict[str, Any],
    alternative: dict[str, Any],
    metadata: dict[str, Any],
) -> float | None:
    for value in (
        channel.get("language_confidence"),
        alternative.get("language_confidence"),
        metadata.get("language_confidence"),
    ):
        confidence = _float_or_none(value)
        if confidence is not None:
            return confidence
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _speaker_if_consistent(words: list[dict[str, Any]]) -> int | None:
    speakers = {_int_or_none(word.get("speaker")) for word in words}
    speakers.discard(None)
    if len(speakers) == 1:
        return next(iter(speakers))
    return None


def _provider_error_message(response: httpx.Response) -> str:
    body = response.text.strip()
    if len(body) > 500:
        body = f"{body[:500]}..."
    return f"Deepgram request failed with status {response.status_code}: {body or response.reason_phrase}"
