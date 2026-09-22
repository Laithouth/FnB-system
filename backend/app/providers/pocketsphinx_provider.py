"""PocketSphinx provider: the default, verified-offline engine.

Why this is the default in *this* environment: PocketSphinx ships its
acoustic model, dictionary, and language model inside the `pocketsphinx`
pip wheel itself (see `pocketsphinx.get_model_path()`), so it needs zero
network access beyond `pip install`. Everything else evaluated for this
project (faster-whisper, Vosk, whisper.cpp, R2T2) fetches multi-hundred-MB
weights from Hugging Face or another model CDN at first run, and every one
of those hosts is blocked by this sandbox's egress policy. PocketSphinx is
therefore the only provider this project can actually run and test
end-to-end right now -- see backend/tests/test_integration_pocketsphinx.py
for a real audio-in, text-out test.

Trade-off to be explicit about: PocketSphinx is a ~15-year-old GMM/HMM
recognizer. Its word error rate on natural conversational speech is
materially worse than a modern neural model (Whisper-family, R2T2) --
expect it to struggle with anything other than clear, close-mic, standard
American English. It is shipped here as a genuinely-working default, not
as a claim that it matches R2T2/Whisper accuracy. For production use,
switch PROVIDER=faster_whisper once you have network access to Hugging
Face (see faster_whisper_provider.py and README.md).

Streaming behavior: uses pocketsphinx's `Endpointer` (a WebRTC-VAD-based
utterance segmenter with built-in pre/post padding) to decide when an
utterance starts/ends, and `Decoder.process_raw(..., full_utt=False)` to
get a cumulative partial hypothesis after every frame while the utterance
is open. That maps directly onto our tentative/committed protocol: every
partial hypothesis while `in_speech` is a `tentative` update for the
current segment id; the hypothesis produced at `end_utt()` is the
`committed` text for that segment.
"""
from __future__ import annotations

import asyncio
import itertools
import logging

from pocketsphinx import Config, Decoder, Endpointer, get_model_path

from ..audio import downmix_to_mono, pcm16_bytes_to_samples, resample_linear, samples_to_pcm16_bytes
from .base import Hypothesis, ProviderCapabilities, TranscriptionProvider, TranscriptionSession

logger = logging.getLogger(__name__)

REQUIRED_SAMPLE_RATE = 16000

# Only en-us ships in the pip wheel; other locales would need their own
# acoustic model downloaded separately (blocked in this sandbox -- see
# module docstring), so we only ever advertise English here.
SUPPORTED_LANGUAGES = ["en"]


class PocketSphinxSession(TranscriptionSession):
    def __init__(self, *, vocabulary_hints: list[str] | None = None) -> None:
        model_path = get_model_path()
        config = Config(
            hmm=f"{model_path}/en-us/en-us",
            lm=f"{model_path}/en-us/en-us.lm.bin",
            dict=f"{model_path}/en-us/cmudict-en-us.dict",
            samprate=REQUIRED_SAMPLE_RATE,
            loglevel="FATAL",
        )
        self._decoder = Decoder(config)
        self._endpointer = Endpointer(sample_rate=REQUIRED_SAMPLE_RATE)
        self._frame_bytes = self._endpointer.frame_bytes
        self._buffer = bytearray()
        self._utt_open = False
        self._segment_ids = itertools.count(1)
        self._current_segment_id: int | None = None
        self._closed = False
        if vocabulary_hints:
            logger.info(
                "PocketSphinx provider does not support contextual vocabulary hints "
                "(ignoring %d hint word(s)); use faster_whisper for hint support.",
                len(vocabulary_hints),
            )

    def _hyp_text(self) -> str:
        hyp = self._decoder.hyp()
        return hyp.hypstr.strip() if hyp is not None else ""

    def _start_segment(self) -> int:
        self._decoder.start_utt()
        self._utt_open = True
        self._current_segment_id = next(self._segment_ids)
        return self._current_segment_id

    def _end_segment(self) -> Hypothesis | None:
        if not self._utt_open:
            return None
        self._decoder.end_utt()
        self._utt_open = False
        segment_id = self._current_segment_id
        self._current_segment_id = None
        text = self._hyp_text()
        return Hypothesis(segment_id=segment_id, text=text, is_final=True)

    def _process_frames(self) -> list[Hypothesis]:
        results: list[Hypothesis] = []
        while len(self._buffer) >= self._frame_bytes:
            frame = bytes(self._buffer[: self._frame_bytes])
            del self._buffer[: self._frame_bytes]
            speech = self._endpointer.process(frame)
            if speech is None:
                continue
            if not self._utt_open:
                segment_id = self._start_segment()
            else:
                segment_id = self._current_segment_id
            self._decoder.process_raw(speech, no_search=False, full_utt=False)
            partial = self._hyp_text()
            results.append(Hypothesis(segment_id=segment_id, text=partial, is_final=False))
            if not self._endpointer.in_speech:
                final = self._end_segment()
                if final is not None:
                    results.append(final)
        return results

    async def feed_audio(self, pcm16le_mono: bytes, sample_rate: int) -> list[Hypothesis]:
        if self._closed:
            return []
        if sample_rate != REQUIRED_SAMPLE_RATE:
            # Defensive fallback only -- the client is told to send audio
            # already resampled to REQUIRED_SAMPLE_RATE via the `ready`
            # message's sample_rate field.
            samples = pcm16_bytes_to_samples(pcm16le_mono)
            samples = resample_linear(samples, sample_rate, REQUIRED_SAMPLE_RATE)
            pcm16le_mono = samples_to_pcm16_bytes(samples)
        self._buffer.extend(pcm16le_mono)
        return await asyncio.to_thread(self._process_frames)

    def _pause_sync(self) -> list[Hypothesis]:
        final = self._end_segment()
        self._buffer.clear()
        return [final] if final is not None else []

    async def pause(self) -> list[Hypothesis]:
        if self._closed:
            return []
        return await asyncio.to_thread(self._pause_sync)

    def _finalize_sync(self) -> list[Hypothesis]:
        results: list[Hypothesis] = []
        if len(self._buffer) > 0:
            # Feed a final short frame through the endpointer to flush any
            # trailing speech it's holding onto.
            tail = bytes(self._buffer)
            self._buffer.clear()
            if len(tail) < self._frame_bytes:
                speech = self._endpointer.end_stream(tail)
            else:
                speech = self._endpointer.process(tail[: self._frame_bytes])
            if speech is not None:
                if not self._utt_open:
                    segment_id = self._start_segment()
                else:
                    segment_id = self._current_segment_id
                self._decoder.process_raw(speech, no_search=False, full_utt=False)
                results.append(Hypothesis(segment_id=segment_id, text=self._hyp_text(), is_final=False))
        final = self._end_segment()
        if final is not None:
            results.append(final)
        return results

    async def finalize(self, timeout_s: float) -> list[Hypothesis]:
        if self._closed:
            return []
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._finalize_sync), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("PocketSphinx finalize timed out after %.1fs", timeout_s)
            return []

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._utt_open:
                self._decoder.end_utt()
        except Exception:  # pragma: no cover - defensive cleanup
            pass


class PocketSphinxProvider(TranscriptionProvider):
    name = "pocketsphinx"

    def __init__(self) -> None:
        # Fail fast at startup (not on the first WS connection) if the
        # bundled model can't even be constructed.
        probe = PocketSphinxSession()
        probe.close()
        self._ready = True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_hints=False,
            supports_confidence=False,
            supports_partial_results=True,
            languages=SUPPORTED_LANGUAGES,
            requires_network=False,
            requires_gpu=False,
        )

    def model_name(self) -> str:
        return "pocketsphinx-en-us (bundled acoustic/language model)"

    def start_session(
        self,
        *,
        language: str,
        sample_rate: int,
        vocabulary_hints: list[str] | None = None,
    ) -> TranscriptionSession:
        if language != "en":
            raise ValueError(
                f"PocketSphinx provider only supports 'en' in this deployment, got {language!r}"
            )
        return PocketSphinxSession(vocabulary_hints=vocabulary_hints)

    def is_ready(self) -> bool:
        return self._ready
