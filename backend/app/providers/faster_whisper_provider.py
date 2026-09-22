"""faster-whisper provider: the recommended engine for a real deployment.

**Not verified in this development sandbox.** faster-whisper downloads its
CTranslate2-converted model weights from Hugging Face on first run, and
this sandbox's egress policy blocks huggingface.co outright (confirmed:
`CONNECT huggingface.co` returns 403 from the proxy). There is no GPU in
this sandbox either (`nvidia-smi` is not present). Everything in this file
is real, runnable code -- it is simply untested *here*. Before relying on
it, run `backend/tests/test_integration_faster_whisper.py` (skipped by
default, see its docstring) on a machine with network access to Hugging
Face.

Why this is still the recommended production provider despite that: it is
open source (MIT), runs well on CPU with int8 quantization for small/medium
models and on GPU for large-v3, and its accuracy on natural speech is far
better than pocketsphinx's classical acoustic model. It is the closest
practical substitute for R2T2 that this project can actually ship: R2T2
needs an NVIDIA GPU plus a separate, more restrictive NetEase model-weight
license, and Qwen3-ASR-scale compute; faster-whisper is a well-understood,
liberally licensed, CPU-or-GPU engine most teams can actually deploy.

Streaming design: faster-whisper decodes fixed-length audio chunks (it has
no native incremental/streaming API), so "streaming" here means: run VAD
(webrtcvad, bundled with faster-whisper's `vad_filter`) to detect utterance
boundaries exactly like the pocketsphinx provider does with its Endpointer,
buffer audio for the open utterance, and re-run transcription on the
accumulated buffer every `PARTIAL_INTERVAL_S` seconds to produce an updated
*cumulative* tentative hypothesis (replace, not append -- see reconciler.py),
finalizing with one last decode when the utterance ends. This trades some
latency/CPU (re-decoding the whole open utterance repeatedly) for using a
model that was never designed to stream in the first place; a production
deployment that needs materially lower latency should look at whisper
streaming forks (e.g. whisper_streaming) or a natively-streaming model.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time

from ..audio import pcm16_bytes_to_samples
from .base import Hypothesis, ProviderCapabilities, TranscriptionProvider, TranscriptionSession

logger = logging.getLogger(__name__)

REQUIRED_SAMPLE_RATE = 16000
PARTIAL_INTERVAL_S = 1.0
MAX_UTTERANCE_S = 30.0

# faster-whisper/Whisper supports far more languages than this, but this
# project only advertises the languages the product spec asked us to
# evaluate. Extend deliberately, and re-test WER before adding one to
# TESTED_LANGUAGES in config.py.
SUPPORTED_LANGUAGES = ["en", "ar", "fr", "es"]


class FasterWhisperSession(TranscriptionSession):
    def __init__(self, model, *, language: str, vocabulary_hints: list[str] | None):
        self._model = model
        self._language = language
        self._initial_prompt = ", ".join(vocabulary_hints) if vocabulary_hints else None
        self._segment_ids = itertools.count(1)
        self._current_segment_id: int | None = None
        self._buffer = bytearray()
        self._last_partial_at = 0.0
        self._closed = False

        # webrtcvad ships as a transitive dependency of faster-whisper's
        # vad_filter; imported lazily so this module can be imported (for
        # documentation/tests-that-skip) without faster-whisper installed.
        import webrtcvad

        self._vad = webrtcvad.Vad(2)
        self._vad_frame_bytes = int(REQUIRED_SAMPLE_RATE * 0.03) * 2  # 30ms frames
        self._vad_carry = bytearray()
        self._in_speech = False
        self._silence_run = 0

    def _is_speech_frame(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, REQUIRED_SAMPLE_RATE)

    def _transcribe_buffer(self, is_final: bool) -> str:
        samples = pcm16_bytes_to_samples(bytes(self._buffer))
        audio = [s / 32768.0 for s in samples]
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            initial_prompt=self._initial_prompt,
            vad_filter=False,  # we already gated on VAD ourselves
            beam_size=1 if not is_final else 5,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def _process_sync(self, pcm16le_mono: bytes) -> list[Hypothesis]:
        results: list[Hypothesis] = []
        self._vad_carry.extend(pcm16le_mono)

        while len(self._vad_carry) >= self._vad_frame_bytes:
            frame = bytes(self._vad_carry[: self._vad_frame_bytes])
            del self._vad_carry[: self._vad_frame_bytes]
            speech = self._is_speech_frame(frame)

            if speech:
                self._silence_run = 0
                if not self._in_speech:
                    self._in_speech = True
                    self._current_segment_id = next(self._segment_ids)
                    self._buffer.clear()
                self._buffer.extend(frame)

                now = time.monotonic()
                too_long = len(self._buffer) / 2 / REQUIRED_SAMPLE_RATE >= MAX_UTTERANCE_S
                if too_long or now - self._last_partial_at >= PARTIAL_INTERVAL_S:
                    self._last_partial_at = now
                    text = self._transcribe_buffer(is_final=False)
                    results.append(
                        Hypothesis(segment_id=self._current_segment_id, text=text, is_final=False)
                    )
                if too_long:
                    final_text = self._transcribe_buffer(is_final=True)
                    results.append(
                        Hypothesis(segment_id=self._current_segment_id, text=final_text, is_final=True)
                    )
                    self._in_speech = False
                    self._buffer.clear()
            else:
                if self._in_speech:
                    self._silence_run += 1
                    self._buffer.extend(frame)  # trailing padding
                    if self._silence_run >= 10:  # ~300ms of silence ends the utterance
                        final_text = self._transcribe_buffer(is_final=True)
                        results.append(
                            Hypothesis(
                                segment_id=self._current_segment_id, text=final_text, is_final=True
                            )
                        )
                        self._in_speech = False
                        self._buffer.clear()
                        self._silence_run = 0

        return results

    async def feed_audio(self, pcm16le_mono: bytes, sample_rate: int) -> list[Hypothesis]:
        if self._closed:
            return []
        if sample_rate != REQUIRED_SAMPLE_RATE:
            raise ValueError(
                f"faster-whisper session configured for {REQUIRED_SAMPLE_RATE}Hz, got {sample_rate}"
            )
        return await asyncio.to_thread(self._process_sync, pcm16le_mono)

    def _pause_sync(self) -> list[Hypothesis]:
        if not self._in_speech:
            return []
        final_text = self._transcribe_buffer(is_final=True)
        segment_id = self._current_segment_id
        self._in_speech = False
        self._buffer.clear()
        self._vad_carry.clear()
        return [Hypothesis(segment_id=segment_id, text=final_text, is_final=True)]

    async def pause(self) -> list[Hypothesis]:
        if self._closed:
            return []
        return await asyncio.to_thread(self._pause_sync)

    async def finalize(self, timeout_s: float) -> list[Hypothesis]:
        if self._closed:
            return []
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._pause_sync), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("faster-whisper finalize timed out after %.1fs", timeout_s)
            return []

    def close(self) -> None:
        self._closed = True


class FasterWhisperProvider(TranscriptionProvider):
    name = "faster_whisper"

    def __init__(self, *, model_size: str = "small", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel  # optional dependency

        self._model_size = model_size
        # Loaded once, shared read-only across every session's transcribe()
        # calls (CTranslate2 models are safe for concurrent inference calls
        # from multiple threads) -- this is the "reuse loaded model weights
        # across sessions" the product spec asks for; per-session state
        # (the VAD buffer/segment ids) lives entirely in FasterWhisperSession.
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._ready = True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_hints=True,
            supports_confidence=True,
            supports_partial_results=True,
            languages=SUPPORTED_LANGUAGES,
            requires_network=True,  # first-run model download from Hugging Face
            requires_gpu=False,  # supported but not required
        )

    def model_name(self) -> str:
        return f"faster-whisper ({self._model_size})"

    def start_session(
        self,
        *,
        language: str,
        sample_rate: int,
        vocabulary_hints: list[str] | None = None,
    ) -> TranscriptionSession:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"faster_whisper provider does not support language {language!r}")
        return FasterWhisperSession(self._model, language=language, vocabulary_hints=vocabulary_hints)

    def is_ready(self) -> bool:
        return self._ready
