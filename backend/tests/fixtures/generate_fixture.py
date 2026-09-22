"""Regenerates sample_speech_16k_mono.wav from real synthesized speech.

Requires espeak-ng (`apt-get install espeak-ng` / `brew install espeak-ng`).
This produces genuinely synthesized speech audio (not silence, not noise,
not a hand-crafted signal) so the integration test in
test_integration_pocketsphinx.py exercises the real decoder against real
(if slightly robotic) speech, with no live microphone required.

Usage:
    python3 tests/fixtures/generate_fixture.py
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.audio import pcm16_bytes_to_samples, resample_linear, samples_to_pcm16_bytes  # noqa: E402

TEXT = (
    "Please go forward ten meters and then turn left at the very very "
    "important intersection near the number seven building"
)
RAW_PATH = Path("/tmp/live_transcriber_fixture_raw.wav")
OUT_PATH = Path(__file__).parent / "sample_speech_16k_mono.wav"


def main() -> None:
    subprocess.run(
        ["espeak-ng", "-v", "en-us", "-s", "150", "-w", str(RAW_PATH), TEXT],
        check=True,
    )

    with wave.open(str(RAW_PATH), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        src_rate = w.getframerate()
        pcm = w.readframes(w.getnframes())

    samples = pcm16_bytes_to_samples(pcm)
    resampled = resample_linear(samples, src_rate, 16000)
    pcm16k = samples_to_pcm16_bytes(resampled)

    with wave.open(str(OUT_PATH), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(pcm16k)

    print(f"wrote {OUT_PATH} ({len(pcm16k)} bytes, {len(pcm16k) / 2 / 16000:.2f}s)")


if __name__ == "__main__":
    main()
