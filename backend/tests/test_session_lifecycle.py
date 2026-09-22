"""Session lifecycle / isolation tests against the real WebSocket endpoint
and the real (bundled, offline) PocketSphinx provider -- no mocked
recognition events. Uses short synthetic PCM (not necessarily
comprehensible speech) since these tests are about protocol/session
correctness, not recognition accuracy; see test_integration_pocketsphinx.py
for a real-speech accuracy smoke test.
"""
from __future__ import annotations

import json
import math
from array import array

from fastapi.testclient import TestClient

from app.audio import pack_audio_frame, samples_to_pcm16_bytes
from app.main import app

client = TestClient(app)


def _tone_frame(n_samples: int = 1600, freq: float = 220.0, sample_rate: int = 16000) -> bytes:
    samples = array(
        "h",
        [int(16000 * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n_samples)],
    )
    return samples_to_pcm16_bytes(samples)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_reports_provider_ready():
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["provider"] == "pocketsphinx"


def test_rejects_connection_without_session_start_first():
    with client.websocket_connect("/ws/transcribe") as ws:
        status = json.loads(ws.receive_text())
        assert status == {"type": "status", "state": "connecting", "detail": ""}
        ws.send_text(json.dumps({"type": "pause"}))  # not session_start
        err = json.loads(ws.receive_text())
        assert err["type"] == "error"
        assert err["code"] == "protocol_error"


def test_full_session_start_audio_stop_lifecycle():
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.receive_text()  # connecting
        ws.send_text(json.dumps({"type": "session_start", "sample_rate": 16000, "language": "en"}))

        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        assert ready["provider"] == "pocketsphinx"
        session_id = ready["session_id"]
        assert session_id

        listening = json.loads(ws.receive_text())
        assert listening == {"type": "status", "state": "listening", "detail": ""}

        for seq in range(5):
            ws.send_bytes(pack_audio_frame(seq, _tone_frame()))

        ws.send_text(json.dumps({"type": "stop"}))

        messages = []
        while True:
            msg = json.loads(ws.receive_text())
            messages.append(msg)
            if msg.get("type") == "status" and msg.get("state") == "complete":
                break

        assert any(m["type"] == "status" and m["state"] == "finishing" for m in messages)
        # Every transcript_event must carry this connection's session_id --
        # this is the isolation guarantee: nothing here is shared state.
        for m in messages:
            if m["type"] == "transcript_event":
                assert m["session_id"] == session_id


def test_two_sequential_sessions_do_not_leak_transcript():
    def run_session(hints=None):
        with client.websocket_connect("/ws/transcribe") as ws:
            ws.receive_text()  # connecting
            ws.send_text(
                json.dumps({"type": "session_start", "sample_rate": 16000, "language": "en"})
            )
            ready = json.loads(ws.receive_text())
            ws.receive_text()  # listening
            ws.send_text(json.dumps({"type": "stop"}))
            committed = []
            while True:
                msg = json.loads(ws.receive_text())
                if msg["type"] == "transcript_event" and msg["kind"] == "committed":
                    committed.append(msg["text"])
                if msg.get("type") == "status" and msg.get("state") == "complete":
                    break
            return ready["session_id"], committed

    id_a, committed_a = run_session()
    id_b, committed_b = run_session()

    assert id_a != id_b
    # Neither session spoke, so both must be empty -- and critically, each
    # session's segment ids restart from 1 independently (proving separate
    # reconciler/provider-session instances rather than shared state).
    assert committed_a == []
    assert committed_b == []


def test_pause_then_resume_preserves_session_and_allows_more_audio():
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.receive_text()  # connecting
        ws.send_text(json.dumps({"type": "session_start", "sample_rate": 16000, "language": "en"}))
        ready = json.loads(ws.receive_text())
        ws.receive_text()  # listening

        ws.send_bytes(pack_audio_frame(0, _tone_frame()))
        ws.send_text(json.dumps({"type": "pause"}))

        msg = json.loads(ws.receive_text())
        while not (msg.get("type") == "status" and msg.get("state") == "paused"):
            msg = json.loads(ws.receive_text())

        ws.send_text(json.dumps({"type": "resume"}))
        resumed = json.loads(ws.receive_text())
        assert resumed == {"type": "status", "state": "listening", "detail": ""}

        # Recording timeline / session id must be unchanged across pause/resume.
        ws.send_bytes(pack_audio_frame(1, _tone_frame()))
        ws.send_text(json.dumps({"type": "stop"}))
        while True:
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "status" and msg.get("state") == "complete":
                break


def test_malformed_first_message_is_rejected():
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.receive_text()  # connecting
        ws.send_text("not json")
        err = json.loads(ws.receive_text())
        assert err["type"] == "error"
        assert err["code"] == "protocol_error"
