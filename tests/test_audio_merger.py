import json
import math
import shutil
import struct
import subprocess
import wave

import pytest
from app.services.tts.audio_merger import AudioMetadata, merge_chapter_audio, merge_book_m4b
from app.services.tts.audio_qa import analyze_audio
from app.services.tts import audio_merger

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


def tone(path, rate=24000):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(i * 2 * math.pi * 440 / rate))) for i in range(rate)))


def test_mixed_formats_keep_gap_and_apply_rate_once(tmp_path):
    first, wav, second = tmp_path / "one.wav", tmp_path / "two.wav", tmp_path / "two.mp3"
    tone(first)
    tone(wav, 44100)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), str(second)], check=True)
    merged = merge_chapter_audio([first, second], tmp_path / "merged.mp3", metadata=AudioMetadata(), rate="-50%", silence_ms=350)
    qa = analyze_audio(merged)
    assert qa.passed and 4.65 <= qa.duration_seconds <= 4.85


def test_m4b_contains_chapter_titles_and_boundaries(tmp_path, monkeypatch):
    paths = [tmp_path / "one.wav", tmp_path / "two.wav"]
    for path in paths:
        tone(path)
    calls = []
    run = subprocess.run
    def tracked(args, **kwargs):
        calls.append(args)
        return run(args, **kwargs)
    monkeypatch.setattr(audio_merger.subprocess, 'run', tracked)
    output = merge_book_m4b(paths, tmp_path / "book.m4b", metadata=AudioMetadata(title="Book"), chapter_titles=["Một", "Hai"])
    assert len(calls) == 1 and 'pcm_s16le' not in calls[0]
    result = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json", str(output)], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert [item["tags"]["title"] for item in payload["chapters"]] == ["Một", "Hai"]
    assert abs(float(payload["chapters"][1]["start_time"]) - 1) < .1
    assert abs(float(payload["format"]["duration"]) - 2) < .1


def test_normalized_wav_merge_uses_only_silence_and_encoder(tmp_path, monkeypatch):
    source = tmp_path / "tone.wav"
    tone(source)
    calls = []
    run = subprocess.run
    def tracked(args, **kwargs):
        calls.append(args)
        return run(args, **kwargs)
    monkeypatch.setattr(audio_merger.subprocess, 'run', tracked)
    merged = merge_chapter_audio([source] * 8, tmp_path / "chapter.mp3", metadata=AudioMetadata())
    assert len(calls) == 2 and all('pcm_s16le' not in args for args in calls)
    qa = analyze_audio(merged)
    assert qa.passed and abs(qa.duration_seconds - (8 + 7 * .35)) < .1


@pytest.mark.parametrize('channels,width,rate', [(2, 2, 24000), (1, 1, 24000), (1, 2, 44100)])
def test_other_pcm_formats_are_normalized(tmp_path, channels, width, rate):
    source = tmp_path / "other.wav"
    with wave.open(str(source), 'wb') as wav:
        wav.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(bytes([128]) * (channels * width * rate))
    decoded = audio_merger._decode_pcm([source], tmp_path)[0]
    assert decoded != source
    with wave.open(str(decoded), 'rb') as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.getnframes() > 0


def test_truncated_pcm_is_decoded_and_bad_input_preserves_existing_output(tmp_path):
    source = tmp_path / "truncated.wav"
    tone(source)
    source.write_bytes(source.read_bytes()[:100])
    assert audio_merger._decode_pcm([source], tmp_path)[0] != source
    source.write_bytes(b'not audio')
    output = tmp_path / 'published.mp3'
    output.write_bytes(b'previous published audio')
    with pytest.raises(RuntimeError, match='could not decode'):
        merge_chapter_audio([source], output, metadata=AudioMetadata())
    assert output.read_bytes() == b'previous published audio'
    assert not list(tmp_path.glob('tts-merge-*'))
