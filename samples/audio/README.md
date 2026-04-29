# Audio Test Samples

These files are small public voice/audio samples for manual end-to-end testing of the transcription pipeline.

## Files

| File                     | Format     | Source                                                  |
| ------------------------ | ---------- | ------------------------------------------------------- |
| `voice-sample.mp3`       | MP3        | https://sample-files.com/audio/mp3/                     |
| `voice-sample.wav`       | WAV        | https://sample-files.com/audio/wav/                     |
| `voice-sample.flac`      | FLAC       | https://sample-files.com/audio/flac/                    |
| `voice-sample.ogg`       | OGG Vorbis | https://sample-files.com/audio/ogg/                     |
| `voice-sample.m4a`       | M4A / AAC  | https://sample-files.com/audio/m4a/                     |
| `deepgram-spacewalk.wav` | WAV        | https://developers.deepgram.com/docs/pre-recorded-audio |

The `voice-sample.*` files are intended for upload format smoke tests. The Deepgram sample is useful for both local file upload and remote URL testing.

## File Upload Test

```bash
curl -X POST http://localhost:8000/transcriptions \
  -F "file=@samples/audio/voice-sample.mp3"
```

Repeat with:

```text
samples/audio/voice-sample.wav
samples/audio/voice-sample.flac
samples/audio/voice-sample.ogg
samples/audio/voice-sample.m4a
samples/audio/deepgram-spacewalk.wav
```

## Remote URL Test

```bash
curl -X POST http://localhost:8000/transcriptions \
  -H "Content-Type: application/json" \
  -d "{\"audio_url\":\"https://dpgr.am/spacewalk.wav\"}"
```

## Base64 Test

PowerShell:

```powershell
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("samples/audio/voice-sample.mp3"))
$body = @{ audio_base64 = "data:audio/mpeg;base64,$b64" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/transcriptions" -ContentType "application/json" -Body $body
```

## Polling

```bash
curl http://localhost:8000/transcriptions/<job_id>
```

Expect `status` to move from `queued` to `processing` or `retrying`, then `completed` with `text` and `segments`. Segment timestamps should have numeric `start` and `end` values.
