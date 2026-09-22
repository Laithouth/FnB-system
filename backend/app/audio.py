"""Audio frame (de)serialization and format conversion.

The frontend always sends mono 16-bit PCM at the provider's requested
sample rate (resampling happens client-side, in the AudioWorklet pipeline,
so the backend never has to guess the browser's native rate). These helpers
still validate that invariant defensively and provide a resampler for
non-browser callers (tests, file-based integration tests, future upload
support) that hand in arbitrary WAV data.
"""
from __future__ import annotations

import struct
from array import array

from .protocol import AUDIO_HEADER_FORMAT, AUDIO_HEADER_SIZE


class AudioFrameError(ValueError):
    pass


def pack_audio_frame(seq: int, pcm16le: bytes, frame_type: int = 0) -> bytes:
    return struct.pack(AUDIO_HEADER_FORMAT, seq, frame_type) + pcm16le


def unpack_audio_frame(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < AUDIO_HEADER_SIZE:
        raise AudioFrameError(f"frame too short: {len(data)} bytes")
    seq, frame_type = struct.unpack(AUDIO_HEADER_FORMAT, data[:AUDIO_HEADER_SIZE])
    payload = data[AUDIO_HEADER_SIZE:]
    if len(payload) % 2 != 0:
        raise AudioFrameError("PCM16 payload must have an even byte length")
    return seq, frame_type, payload


def pcm16_bytes_to_samples(pcm16le: bytes) -> array:
    samples = array("h")
    samples.frombytes(pcm16le)
    return samples


def samples_to_pcm16_bytes(samples: array) -> bytes:
    return samples.tobytes()


def downmix_to_mono(samples: array, channels: int) -> array:
    """Average interleaved multi-channel int16 samples down to mono."""
    if channels <= 1:
        return samples
    if len(samples) % channels != 0:
        raise AudioFrameError(
            f"sample count {len(samples)} is not divisible by channel count {channels}"
        )
    mono = array("h")
    for i in range(0, len(samples), channels):
        frame = samples[i : i + channels]
        mono.append(int(sum(frame) / channels))
    return mono


def resample_linear(samples: array, src_rate: int, dst_rate: int) -> array:
    """Simple linear-interpolation resampler.

    Good enough for speech-band PCM going into a decoder that itself only
    needs roughly-correct timing (pocketsphinx/whisper are both tolerant of
    minor resampling artifacts); not intended as a mastering-grade DSP
    resampler. Used for test fixtures and any provider fed audio that isn't
    already at its target rate.
    """
    if src_rate == dst_rate or len(samples) == 0:
        return samples
    src_len = len(samples)
    dst_len = int(round(src_len * dst_rate / src_rate))
    out = array("h", [0]) * dst_len
    scale = (src_len - 1) / (dst_len - 1) if dst_len > 1 else 0.0
    for i in range(dst_len):
        pos = i * scale
        lo = int(pos)
        hi = min(lo + 1, src_len - 1)
        frac = pos - lo
        val = samples[lo] * (1 - frac) + samples[hi] * frac
        out[i] = max(-32768, min(32767, int(round(val))))
    return out


def rms_dbfs(samples: array) -> float:
    """Root-mean-square level in dBFS, for the level meter / silence checks."""
    if len(samples) == 0:
        return -120.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq <= 0:
        return -120.0
    import math

    rms = math.sqrt(mean_sq) / 32768.0
    if rms <= 0:
        return -120.0
    return max(-120.0, 20 * math.log10(rms))
