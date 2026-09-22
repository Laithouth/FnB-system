"""Per-connection recording session: owns exactly one provider session, one
reconciler, and one bounded audio queue. A WebSocket connection *is* a
session (1:1) -- this is what makes session isolation structural rather
than something we have to remember to enforce: nothing here is shared
mutable state across connections except the read-only `TranscriptionProvider`
factory, which only ever hands out fresh, independent `TranscriptionSession`
objects.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from .config import settings
from .protocol import AppState
from .providers.base import Hypothesis, TranscriptionProvider, TranscriptionSession
from .reconciler import TranscriptReconciler

logger = logging.getLogger(__name__)


class RecordingState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PAUSED = "paused"
    FINISHING = "finishing"
    COMPLETE = "complete"
    CLOSED = "closed"


@dataclass
class DropStats:
    dropped_frames: int = 0
    last_reported_at: float = field(default_factory=time.monotonic)


class Session:
    """One live recording session. Not thread-safe by design -- it is only
    ever touched from its own asyncio task (the WebSocket handler and its
    one background consumer task, both on the same event loop)."""

    def __init__(self, provider: TranscriptionProvider, provider_session: TranscriptionSession):
        self.session_id = str(uuid.uuid4())
        self.provider = provider
        self.provider_session = provider_session
        self.reconciler = TranscriptReconciler()
        self.state = RecordingState.LISTENING
        self.started_at = time.monotonic()
        self._seq = itertools.count(1)
        # Single ordered work queue for BOTH audio frames and control
        # commands (pause/resume/stop). Everything that must touch
        # provider_session goes through this one queue, drained by one
        # consumer task (see main.py:audio_processor) -- that is what
        # guarantees pocketsphinx's non-thread-safe Decoder (and any other
        # provider) is only ever called from a single task, and that a Stop
        # is only finalized *after* every audio frame received before it
        # has actually been decoded, not out of order.
        self._work_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=settings.max_queued_frames)
        # A single dedicated sender task owns the actual WebSocket.send()
        # calls, fed by this queue, so control replies (status, errors) and
        # transcript events -- produced from two different tasks -- never
        # race writing to the same socket.
        self._outbound_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._drop_stats = DropStats()
        self._closed = False

    def next_seq(self) -> int:
        return next(self._seq)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def enqueue_audio(self, frame: bytes) -> bool:
        """Non-blocking enqueue. Returns False if the bounded queue is full
        and this frame had to be dropped (caller should surface that to the
        client rather than pretending nothing happened). Audio is the only
        thing ever dropped here -- control commands use enqueue_control,
        which blocks instead, so a Stop can never be lost."""
        try:
            self._work_queue.put_nowait({"kind": "audio", "payload": frame})
            return True
        except asyncio.QueueFull:
            self._drop_stats.dropped_frames += 1
            return False

    async def enqueue_control(self, kind: str) -> None:
        await self._work_queue.put({"kind": kind})

    @property
    def dropped_frames(self) -> int:
        return self._drop_stats.dropped_frames

    async def next_work_item(self) -> dict:
        return await self._work_queue.get()

    def send_nowait(self, message: dict) -> None:
        self._outbound_queue.put_nowait(message)

    async def next_outbound(self) -> dict:
        return await self._outbound_queue.get()

    async def apply_hypotheses(self, hyps: list[Hypothesis]) -> list[dict]:
        """Run each hypothesis through the reconciler, returning the
        protocol-level transcript_event payloads that should actually be
        sent (duplicates/stale updates are filtered out here)."""
        events: list[dict] = []
        for hyp in hyps:
            if hyp.is_final:
                result = self.reconciler.commit_segment(
                    hyp.segment_id, hyp.text, hyp.start_ms, hyp.end_ms
                )
            else:
                result = self.reconciler.update_tentative(hyp.segment_id, hyp.text)
            if result.emit is not None:
                events.append(result.emit)
        return events

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.state = RecordingState.CLOSED
        try:
            self.provider_session.close()
        except Exception:  # pragma: no cover - defensive cleanup
            logger.exception("error closing provider session %s", self.session_id)


class SessionManager:
    """Tracks active sessions for the readiness/health endpoint and
    enforces a concurrency ceiling so one deployment can't be driven into
    unbounded memory/CPU use by runaway connections."""

    def __init__(self, provider: TranscriptionProvider):
        self.provider = provider
        self._sessions: dict[str, Session] = {}

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def can_accept(self) -> bool:
        return self.active_count < settings.max_concurrent_sessions

    def create_session(
        self, *, language: str, sample_rate: int, vocabulary_hints: list[str] | None
    ) -> Session:
        provider_session = self.provider.start_session(
            language=language, sample_rate=sample_rate, vocabulary_hints=vocabulary_hints
        )
        session = Session(self.provider, provider_session)
        self._sessions[session.session_id] = session
        return session

    def remove_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()
