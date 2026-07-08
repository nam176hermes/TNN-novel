from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ignore_dotenv() -> bool:
    return os.getenv("NOVEL_PIPELINE_IGNORE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None if _ignore_dotenv() else PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:14b"
    ollama_api_key: str = ""
    ollama_temperature: float = 0.3
    ollama_chunk_size: int = 3500
    ollama_timeout: int = 180

    edge_tts_voice: str = "vi-VN-HoaiMyNeural"

    tts_provider: str = "f5_vietnamese"
    tts_model: str = "vivioice"
    tts_model_repo: str = "hynt/F5-TTS-Vietnamese-ViVoice"
    tts_ckpt_file: str = ""
    tts_vocab_file: str = ""
    tts_device: str = "cuda"
    tts_normalizer: str = "vinorm"
    tts_output_format: str = "mp3"
    tts_chunk_max_chars: int = 450
    tts_chunk_max_sentences: int = 4
    tts_reference_audio_path: str = ""
    tts_reference_text: str = ""
    tts_audio_sample_rate: int = 24000
    tts_enable_qa: bool = True
    tts_enable_m4b: bool = True
    tts_cache: bool = True
    tts_chunk_timeout_seconds: int = 120
    tts_chunk_retries: int = 2
    tts_qa_retries: int = 2

    data_dir: Path = Path("data")
    log_level: str = "INFO"

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir.is_absolute():
            return self.data_dir
        return PROJECT_ROOT / self.data_dir

    @property
    def db_path(self) -> Path:
        return self.resolved_data_dir / "pipeline.db"


settings = Settings()
