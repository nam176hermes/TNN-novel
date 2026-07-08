# Local Vietnamese TTS Pipeline

This app now has an additive local TTS pipeline for translated Vietnamese chapters. It is designed for the current single-operator app and does not replace the translation pipeline.

## Runtime Flow

Vietnamese translated chapter text:

1. normalize text with `TTS_NORMALIZER`
2. split into stable sentence/paragraph chunks
3. synthesize each chunk with the configured local TTS engine
4. run audio QA for each chunk
5. merge chunks into one chapter MP3
6. optionally merge chapter MP3s into an M4B audiobook
7. write a JSON report under `data/audio/tts_jobs/<job_id>/report.json`

Existing `/api/jobs/tts` still works. It now records additional `tts_jobs` and `tts_chunks` metadata.

## Environment

Copy `.env.example` to `.env` and configure:

```env
TTS_PROVIDER=f5_vietnamese
TTS_MODEL=vivioice
TTS_MODEL_REPO=hynt/F5-TTS-Vietnamese-ViVoice
TTS_CKPT_FILE=
TTS_VOCAB_FILE=
TTS_DEVICE=cuda
TTS_NORMALIZER=vinorm
TTS_OUTPUT_FORMAT=mp3
TTS_CHUNK_MAX_CHARS=450
TTS_CHUNK_MAX_SENTENCES=4
TTS_REFERENCE_AUDIO_PATH=/path/to/reference.wav
TTS_REFERENCE_TEXT="Đoạn transcript khớp với file reference audio."
TTS_AUDIO_SAMPLE_RATE=24000
TTS_ENABLE_QA=true
TTS_ENABLE_M4B=true
TTS_CACHE=true
```

Do not hardcode model paths in code. Use env/config for model and reference voice assets.
When `TTS_MODEL=vivioice` and `TTS_CKPT_FILE` / `TTS_VOCAB_FILE` are empty, the app resolves `model_last.pt` and `config.json` from `TTS_MODEL_REPO`.

For public/offline deploy, pin the ViVoice model locally so first boot does not require network access:

```bash
mkdir -p data/models/tts/vivoice
SNAPSHOT_DIR="$(ls -dt ~/.cache/huggingface/hub/models--hynt--F5-TTS-Vietnamese-ViVoice/snapshots/* | head -n 1)"
cp -L "$SNAPSHOT_DIR/model_last.pt" data/models/tts/vivoice/model_last.pt
cp -L "$SNAPSHOT_DIR/config.json" data/models/tts/vivoice/vocab.txt
```

Then set:

```env
TTS_CKPT_FILE=data/models/tts/vivoice/model_last.pt
TTS_VOCAB_FILE=data/models/tts/vivoice/vocab.txt
```

## Install F5-TTS / ViVoice

Install F5-TTS in the app environment following the upstream project instructions. The recommended ViVoice checkpoint is `hynt/F5-TTS-Vietnamese-ViVoice`; set local checkpoint paths only when you want to pin an offline copy:

```bash
python -m pip install f5-tts vinorm VietNormalizer
```

The Python integration uses:

```python
from f5_tts.api import F5TTS
f5tts = F5TTS(device="cuda")
f5tts.infer(ref_file="voice.wav", ref_text="...", gen_text="...", file_wave="chunk.wav")
```

If CUDA is requested but unavailable, the wrapper falls back to CPU and logs a warning. F5-TTS needs a valid reference audio file and matching reference text.

## Production Reference Voice

The included local reference file is only a smoke-test placeholder. For audiobook quality, record or provide a clean human Vietnamese reference:

- WAV preferred, mono, 24 kHz or higher source quality.
- 5-15 seconds of natural speech, no music, no echo, no background noise.
- Transcript must match the audio exactly, including punctuation.
- Do not use copyrighted voice samples unless you have rights to use them.

Configure:

```env
TTS_REFERENCE_AUDIO_PATH=data/tts/reference/my-human-reference.wav
TTS_REFERENCE_TEXT="Exact transcript spoken in the reference audio."
```

Verify the file before running jobs:

```bash
ffprobe -v error -show_entries format=duration -of default=nw=1 "$TTS_REFERENCE_AUDIO_PATH"
```

## Install Text Normalization

Preferred normalizers:

- `vinorm`
- `VietNormalizer` / `viet_normalizer`

If neither package is installed, the app uses a rule-based fallback that cleans HTML/markdown/emoji, normalizes Vietnamese punctuation, reads common numbers, and handles chapter headings such as `Chương 123`.

## Install FFmpeg

`ffmpeg` is required to merge chunks and create M4B files.

Verify:

```bash
ffmpeg -version
ffprobe -version
```

If FFmpeg is missing, TTS generation fails with a clear setup error before export/merge.

## Generate Audio

One chapter:

```bash
python3 -m app.tts.generate_chapter --book-id 1 --chapter-id 10
```

Whole book and M4B:

```bash
python3 -m app.tts.generate_book --book-id 1 --format m4b
```

Retry failed chunks:

```bash
python3 -m app.tts.retry_job --job-id tts_job_id
```

API:

```http
POST /api/tts/chapter
GET /api/tts/jobs/{job_id}
POST /api/tts/jobs/{job_id}/retry
POST /api/tts/jobs/{job_id}/cancel
GET /api/tts/jobs/{job_id}/download?format=mp3
```

The legacy job endpoint remains:

```http
POST /api/jobs/tts
```

## Resume and Cache

Chunks are stored in `tts_chunks` with stable `chunk_index`, text hash, output path, QA status, and errors. If a job is retried with the same text and voice config, completed chunk files are reused. F5 chunk cache keys are based on normalized text, voice config, and model config.

## Debug Common Failures

- `F5-TTS is not installed`: install the local model package in the Python environment.
- `TTS_REFERENCE_AUDIO_PATH is required`: configure a local reference WAV.
- `TTS_REFERENCE_TEXT is required`: provide transcript matching the reference audio.
- `ffmpeg is required`: install FFmpeg and ensure it is in `PATH`.
- `Audio appears silent`: check reference voice quality, model output, and device setup.
- `Audio duration is short/long for text length`: reduce `TTS_CHUNK_MAX_CHARS` or inspect the chunk report.

## Compatibility Note

The current app remains single-operator. TTS metadata does not add tenant isolation. Existing Edge TTS behavior is retained only as a compatibility fallback for the old job path when local F5 is not configured; the recommended production path is local `TTS_PROVIDER=f5_vietnamese`.
