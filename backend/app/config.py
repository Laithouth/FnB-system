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
    # Which provider backs live transcription. "faster_whisper" (the
    # default) gives materially better accuracy -- needed for recognizing
    # menu items/order vocabulary reliably -- but requires downloading
    # model weights from Hugging Face on first run and a machine with
    # enough CPU/GPU headroom. "pocketsphinx" runs fully offline (model
    # bundled in the pip wheel); it's the only provider verified to work in
    # network-restricted environments, which is why this project's own test
    # suite pins it via tests/conftest.py regardless of this default -- see
    # README section 2.
    provider: str = field(default_factory=lambda: os.environ.get("PROVIDER", "faster_whisper"))

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

    # Order-domain vocabulary hints applied to every session by default (in
    # addition to whatever hints the client sends in session_start -- the
    # two lists are unioned, not replaced, in main.py). Only the active
    # provider's `supports_hints` capability actually uses these --
    # pocketsphinx ignores them entirely (see PocketSphinxSession). This is
    # a generic drive-thru/QSR starting point, not any specific restaurant's
    # real menu -- override with a real menu's item/modifier names via
    # DEFAULT_VOCABULARY_HINTS for an actual deployment.
    default_vocabulary_hints: list[str] = field(
        default_factory=lambda: _list(
            "DEFAULT_VOCABULARY_HINTS",
            [
                "combo", "upsize", "value meal", "drive-thru", "to go", "for here",
                "small", "medium", "large", "extra large",
                "no onions", "no pickles", "extra cheese", "light ice", "no mayo",
                "diet", "zero sugar", "side of fries", "dipping sauce", "add bacon",
                "gluten free", "order number", "combo number",
            ],
        )
    )

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


def merge_vocabulary_hints(client_hints: list[str], default_hints: list[str]) -> list[str]:
    """Union a session's own hints (e.g. a specific restaurant's menu) with
    the server's default order-vocabulary hints -- neither list replaces
    the other. Client hints come first (more specific, so they win any
    provider-side truncation); duplicates are dropped case-insensitively,
    first occurrence kept, order otherwise preserved."""
    seen: set[str] = set()
    merged: list[str] = []
    for hint in [*client_hints, *default_hints]:
        cleaned = hint.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            merged.append(cleaned)
    return merged
