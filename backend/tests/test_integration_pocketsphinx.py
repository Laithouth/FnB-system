"""Real audio in, real text out -- no mocked/simulated recognition.

This is the acceptance evidence for "genuine speech recognition" (product
spec section 14) that can actually run in this network-restricted sandbox:
it streams a committed WAV fixture through the real PocketSphinxSession the
same way the WebSocket layer does (small chunks, not one big buffer) and
asserts real words come out.

Caveat this test is honest about: the fixture is synthesized speech
(espeak-ng, a formant synthesizer), not a human recording -- see
fixtures/generate_fixture.py. PocketSphinx's word error rate on synthetic,
slightly robotic audio is worse than on a clear human voice, so this test
only asserts that *some* recognizable, non-trivial words appear, not a WER
threshold. A live-microphone/human-speech accuracy pass is unverified in
this sandbox (no microphone or audio input device here) -- see
README.md "Testing" for exact manual steps to run that yourself.
"""
from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from app.providers.pocketsphinx_provider import PocketSphinxSession

FIXTURE = Path(__file__).parent / "fixtures" / "sample_speech_16k_mono.wav"
CHUNK_BYTES = 3200  # 100ms at 16kHz mono 16-bit


def _load_fixture_pcm() -> bytes:
    with wave.open(str(FIXTURE), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        return w.readframes(w.getnframes())


def test_fixture_exists_and_is_real_audio():
    assert FIXTURE.exists(), "run tests/fixtures/generate_fixture.py to (re)create it"
    pcm = _load_fixture_pcm()
    assert len(pcm) > 16000 * 2 * 1  # at least ~1s of audio, sanity check


def test_streaming_transcription_produces_real_committed_text():
    pcm = _load_fixture_pcm()

    async def run():
        session = PocketSphinxSession()
        try:
            all_hyps = []
            for i in range(0, len(pcm), CHUNK_BYTES):
                chunk = pcm[i : i + CHUNK_BYTES]
                all_hyps.extend(await session.feed_audio(chunk, 16000))
            all_hyps.extend(await session.finalize(timeout_s=5.0))
            return all_hyps
        finally:
            session.close()

    hyps = asyncio.run(run())

    finals = [h for h in hyps if h.is_final]
    tentatives = [h for h in hyps if not h.is_final]

    assert len(finals) >= 1, "expected at least one committed segment from real speech"
    assert len(tentatives) > 5, "expected multiple incremental partial updates, not one batch result"

    committed_text = " ".join(h.text for h in finals if h.text).strip()
    assert committed_text, "engine produced no recognizable words at all"

    # Tentative hypotheses for a segment must grow/change over time, not
    # repeat a single static string -- this is the "genuinely incremental,
    # not animated-after-the-fact" requirement (spec section 6).
    distinct_partials = {h.text for h in tentatives}
    assert len(distinct_partials) > 3


def test_segment_ids_are_isolated_per_session_instance():
    """Two independent sessions (as if two different recordings) must not
    share segment-id sequences or decoder state."""
    pcm = _load_fixture_pcm()[: CHUNK_BYTES * 20]

    async def run_once():
        session = PocketSphinxSession()
        try:
            hyps = []
            for i in range(0, len(pcm), CHUNK_BYTES):
                hyps.extend(await session.feed_audio(pcm[i : i + CHUNK_BYTES], 16000))
            hyps.extend(await session.finalize(timeout_s=5.0))
            return hyps
        finally:
            session.close()

    hyps_a = asyncio.run(run_once())
    hyps_b = asyncio.run(run_once())

    ids_a = {h.segment_id for h in hyps_a}
    ids_b = {h.segment_id for h in hyps_b}
    # Both fresh sessions start their segment-id counters at 1 independently.
    assert min(ids_a) == 1
    assert min(ids_b) == 1
