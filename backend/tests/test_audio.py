from array import array

from app.audio import (
    AudioFrameError,
    downmix_to_mono,
    pack_audio_frame,
    pcm16_bytes_to_samples,
    resample_linear,
    rms_dbfs,
    samples_to_pcm16_bytes,
    unpack_audio_frame,
)


def test_pack_unpack_roundtrip():
    payload = samples_to_pcm16_bytes(array("h", [1, -1, 1000, -1000]))
    frame = pack_audio_frame(seq=42, pcm16le=payload)
    seq, frame_type, out_payload = unpack_audio_frame(frame)
    assert seq == 42
    assert frame_type == 0
    assert out_payload == payload


def test_unpack_rejects_short_frame():
    try:
        unpack_audio_frame(b"\x00\x01")
    except AudioFrameError:
        pass
    else:
        raise AssertionError("expected AudioFrameError")


def test_unpack_rejects_odd_length_payload():
    header = pack_audio_frame(seq=1, pcm16le=b"")
    try:
        unpack_audio_frame(header + b"\x01")
    except AudioFrameError:
        pass
    else:
        raise AssertionError("expected AudioFrameError for odd-length PCM payload")


def test_downmix_stereo_averages_channels():
    # L=1000, R=-1000 for two frames -> mono should be ~0
    stereo = array("h", [1000, -1000, 2000, -2000])
    mono = downmix_to_mono(stereo, channels=2)
    assert list(mono) == [0, 0]


def test_downmix_mono_is_noop():
    mono_in = array("h", [1, 2, 3])
    assert downmix_to_mono(mono_in, channels=1) is mono_in


def test_downmix_rejects_mismatched_channel_count():
    try:
        downmix_to_mono(array("h", [1, 2, 3]), channels=2)
    except AudioFrameError:
        pass
    else:
        raise AssertionError("expected AudioFrameError")


def test_resample_preserves_length_ratio():
    src = array("h", [0, 1000, -1000, 2000, -2000, 3000, -3000, 4000] * 100)
    out = resample_linear(src, src_rate=48000, dst_rate=16000)
    expected_len = round(len(src) * 16000 / 48000)
    assert abs(len(out) - expected_len) <= 1


def test_resample_same_rate_is_noop():
    src = array("h", [1, 2, 3])
    assert resample_linear(src, 16000, 16000) is src


def test_resample_upsampling_interpolates():
    src = array("h", [0, 1000])
    out = resample_linear(src, src_rate=8000, dst_rate=16000)
    assert len(out) == 4
    assert out[0] == 0
    assert out[-1] == 1000


def test_rms_dbfs_silence_is_very_low():
    silence = array("h", [0] * 1000)
    assert rms_dbfs(silence) <= -60.0


def test_rms_dbfs_full_scale_is_near_zero():
    loud = array("h", [32767, -32768] * 500)
    assert rms_dbfs(loud) > -1.0


def test_rms_dbfs_empty_array():
    assert rms_dbfs(array("h", [])) == -120.0


def test_pcm16_roundtrip():
    original = array("h", [-32768, -1, 0, 1, 32767])
    data = samples_to_pcm16_bytes(original)
    back = pcm16_bytes_to_samples(data)
    assert list(back) == list(original)
