# TTS Capability

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Live status

Readiness reports TTS unavailable because no supported GPU is available. Core API, Library, Reader, import worker, and storage remain ready. No CPU fallback was observed. [Source] live `/api/ready`; `app/services/tts/f5_vietnamese_engine.py`

## Policy alignment

This matches the required GPU-only F5 and ViVoice policy. Unsupported environments should reject TTS safely while keeping non-TTS workflows usable.

## Untested behavior

No live TTS job or paid provider call was started. Audio quality, real GPU throughput, and long-book M4B generation remain `NOT_TESTED`.

## Privacy issue

`_capture_upstream_output` writes the final 4,000 characters of combined upstream stdout and stderr to DEBUG without applying a content redactor. Upstream output could include input text or paths. See PRIV-TTS-005. [Source] `app/services/tts/f5_vietnamese_engine.py:133-142`

## Verdict

TTS capability: **GO_WITH_LIMITATIONS**. Degradation is honest; GPU execution and privacy logging need focused verification before enabling production TTS.
