"""The application's internal streaming protocol.

This is our contract between the browser client and the backend -- it is
deliberately independent of any single ASR engine's wire format. Each
`TranscriptionProvider` implementation is what maps this protocol onto a
real engine's actual API (see providers/base.py).

Transport: a single WebSocket connection per recording session.
  - JSON text frames carry control messages (both directions).
  - Binary frames carry raw PCM16LE mono audio, each prefixed with an
    8-byte header: seq (uint32 LE) + frame_type (uint32 LE, always 0 for
    now). See audio.py:pack_audio_frame / unpack_audio_frame.

Session/segment identifiers:
  - `session_id` is server-generated (UUID4) and returned in `ready`. The
    client cannot choose it, which prevents one client from colliding with
    or spoofing another session's id.
  - `segment_id` identifies one utterance's worth of transcript. Tentative
    events for a segment all share its id; exactly one commit (or a
    discard, e.g. on VAD false alarm) ends it. Segment ids are monotonic
    within a session so stray events from a stale segment are easy to
    detect and ignore.
  - `seq` is a per-session monotonically increasing integer stamped on
    every server->client event, used purely for client-side ordering /
    duplicate detection -- never for provider-side audio acknowledgement.
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Client -> server (JSON control messages)
# ---------------------------------------------------------------------------


class SessionStart(BaseModel):
    type: Literal["session_start"] = "session_start"
    sample_rate: int = 16000
    channels: int = 1
    language: str = "en"
    model: str | None = None
    vocabulary_hints: list[str] = Field(default_factory=list)


class Pause(BaseModel):
    type: Literal["pause"] = "pause"


class Resume(BaseModel):
    type: Literal["resume"] = "resume"


class Stop(BaseModel):
    type: Literal["stop"] = "stop"


class Ping(BaseModel):
    type: Literal["ping"] = "ping"


ClientMessage = Union[SessionStart, Pause, Resume, Stop, Ping]

_CLIENT_TYPES: dict[str, type[BaseModel]] = {
    "session_start": SessionStart,
    "pause": Pause,
    "resume": Resume,
    "stop": Stop,
    "ping": Ping,
}


def parse_client_message(raw: dict) -> ClientMessage:
    msg_type = raw.get("type")
    model = _CLIENT_TYPES.get(msg_type)
    if model is None:
        raise ValueError(f"unknown client message type: {msg_type!r}")
    return model.model_validate(raw)


# ---------------------------------------------------------------------------
# Server -> client (JSON control messages)
# ---------------------------------------------------------------------------

AppState = Literal[
    "requesting_mic",
    "connecting",
    "loading_model",
    "listening",
    "paused",
    "reconnecting",
    "finishing",
    "complete",
    "error",
]


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    state: AppState
    detail: str = ""


class ReadyMessage(BaseModel):
    type: Literal["ready"] = "ready"
    session_id: str
    provider: str
    model: str
    sample_rate: int
    supports_hints: bool
    supports_confidence: bool


class TranscriptEvent(BaseModel):
    type: Literal["transcript_event"] = "transcript_event"
    session_id: str
    segment_id: int
    seq: int
    kind: Literal["tentative", "committed"]
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None


class AckMessage(BaseModel):
    type: Literal["ack"] = "ack"
    seq: int


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    recoverable: bool = True


ServerMessage = Union[StatusMessage, ReadyMessage, TranscriptEvent, AckMessage, ErrorMessage]

# Binary audio frame header: <uint32 seq><uint32 frame_type>
AUDIO_HEADER_FORMAT = "<II"
AUDIO_HEADER_SIZE = 8
