"""Environment-based configuration. No secrets have defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: list[str]) -> list[str]:
    val = os.environ.get(name)
    if val is None:
        return default
    return [v.strip() for v in val.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Which provider backs live transcription. "pocketsphinx" runs fully
    # offline (model bundled in the pip wheel) and is the only provider
    # verified to work in network-restricted environments. "faster_whisper"
    # gives materially better accuracy but requires downloading model
    # weights from Hugging Face on first run and a machine with enough
    # CPU/GPU headroom -- see backend/README section on providers.
    provider: str = field(default_factory=lambda: os.environ.get("PROVIDER", "pocketsphinx"))

    # faster-whisper model size (tiny/base/small/medium/large-v3). Ignored
    # by the pocketsphinx provider.
    whisper_model_size: str = field(
        default_factory=lambda: os.environ.get("WHISPER_MODEL_SIZE", "small")
    )
    whisper_device: str = field(default_factory=lambda: os.environ.get("WHISPER_DEVICE", "cpu"))
    whisper_compute_type: str = field(
        default_factory=lambda: os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    )

    sample_rate: int = field(default_factory=lambda: int(os.environ.get("SAMPLE_RATE", "16000")))

    # Languages exposed in the UI as "tested" vs "experimental" -- see
    # provider.supported_languages() for what the active provider actually
    # supports; the UI only ever offers the intersection.
    tested_languages: list[str] = field(
        default_factory=lambda: _list("TESTED_LANGUAGES", ["en"])
    )
    experimental_languages: list[str] = field(
        default_factory=lambda: _list("EXPERIMENTAL_LANGUAGES", ["ar", "fr", "es"])
    )

    # Bounded per-session audio queue (frames). When full, the oldest
    # unprocessed frame is dropped and a warning status is sent -- audio is
    # never buffered unboundedly and never silently discarded without
    # telling the client. See session.py.
    max_queued_frames: int = field(
        default_factory=lambda: int(os.environ.get("MAX_QUEUED_FRAMES", "150"))
    )

    # How long (seconds) to wait for the provider to finalize after Stop
    # before giving up and returning whatever is committed so far.
    finalize_timeout_s: float = field(
        default_factory=lambda: float(os.environ.get("FINALIZE_TIMEOUT_S", "8.0"))
    )

    max_reconnect_attempts: int = field(
        default_factory=lambda: int(os.environ.get("MAX_RECONNECT_ATTEMPTS", "3"))
    )

    # Allowed CORS / WebSocket origins for non-localhost deployments.
    allowed_origins: list[str] = field(
        default_factory=lambda: _list("ALLOWED_ORIGINS", ["http://localhost:5173"])
    )

    require_api_key: bool = field(default_factory=lambda: _bool("REQUIRE_API_KEY", False))
    api_key: str | None = field(default_factory=lambda: os.environ.get("API_KEY"))

    max_concurrent_sessions: int = field(
        default_factory=lambda: int(os.environ.get("MAX_CONCURRENT_SESSIONS", "20"))
    )


settings = Settings()
