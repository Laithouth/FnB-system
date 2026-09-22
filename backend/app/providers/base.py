"""Replaceable transcription-provider interface.

Every real engine (pocketsphinx today, faster-whisper for production
deployments, R2T2 in the future once it can actually run) implements this
same interface so the session/WebSocket layer never has to know which
engine is behind it. See providers/pocketsphinx_provider.py and
providers/faster_whisper_provider.py for the two real implementations
shipped with this project, and README.md section "Providers" for why each
one is/isn't verified in this environment.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Hypothesis:
    """One decoding update for the utterance currently open."""

    segment_id: int
    text: str
    is_final: bool
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None


@dataclass
class ProviderCapabilities:
    supports_hints: bool
    supports_confidence: bool
    supports_partial_results: bool
    languages: list[str] = field(default_factory=list)
    requires_network: bool = False
    requires_gpu: bool = False


class TranscriptionSession(ABC):
    """Stateful, per-recording-session decoding. Never share one instance
    of this across two concurrent recordings -- audio/text must not leak
    between sessions (see reconciler tests + session isolation tests)."""

    @abstractmethod
    async def feed_audio(self, pcm16le_mono: bytes, sample_rate: int) -> list[Hypothesis]:
        """Feed one frame of mono PCM16LE audio. Returns zero or more
        hypotheses produced as a direct result of this frame (tentative
        and/or final)."""

    @abstractmethod
    async def pause(self) -> list[Hypothesis]:
        """Stop-for-Pause: finalize whatever utterance is currently open
        (so committed text doesn't get lost) without closing engine
        resources. The session must accept feed_audio again after this and
        start a fresh segment on the next speech it detects."""

    @abstractmethod
    async def finalize(self, timeout_s: float) -> list[Hypothesis]:
        """Signal end-of-stream (drain buffered audio, close the current
        utterance) and return any remaining hypotheses, including a final
        one for whatever utterance was still open. Must return within
        timeout_s even if the engine hasn't produced a clean final result --
        callers use this to implement the "Finishing" timeout / incomplete
        state in the protocol."""

    @abstractmethod
    def close(self) -> None:
        """Release all engine resources held by this session (decoder
        handles, buffers). Must be safe to call more than once."""


class TranscriptionProvider(ABC):
    """Factory + capability advertisement for one ASR engine."""

    name: str

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def start_session(
        self,
        *,
        language: str,
        sample_rate: int,
        vocabulary_hints: list[str] | None = None,
    ) -> TranscriptionSession: ...

    @abstractmethod
    def is_ready(self) -> bool:
        """True once the model is actually loaded and able to decode --
        this backs the /readyz check; it must not just mean the process is
        up."""
