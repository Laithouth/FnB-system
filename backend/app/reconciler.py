"""Transcript reconciliation: turns a provider's raw hypothesis stream into
the append-only committed/tentative event stream the protocol promises.

Rules this enforces (see section 6/7 of the product spec):
  - Committed segment text never changes once emitted.
  - A cumulative hypothesis for the *current* (still-open) segment replaces
    the previous tentative text for that segment -- it is not appended.
  - A stray/late update for an already-committed or unknown segment is
    dropped rather than corrupting the transcript.
  - Legitimate repeated words ("very, very important") are preserved --
    de-duplication is keyed on segment id, never on text content.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommittedSegment:
    segment_id: int
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class ReconcileResult:
    """What changed as a result of feeding the reconciler one event.

    `emit` is the event (if any) that should actually be sent onward --
    duplicate/stale updates yield `emit is None` so callers can skip them.
    """

    emit: dict | None
    full_committed_text: str


@dataclass
class TranscriptReconciler:
    """Pure, provider-agnostic state machine. One instance per session."""

    _committed: list[CommittedSegment] = field(default_factory=list)
    _committed_ids: set[int] = field(default_factory=set)
    _open_segment_id: int | None = None
    _tentative_text: str = ""

    @property
    def committed_segments(self) -> list[CommittedSegment]:
        return list(self._committed)

    @property
    def tentative_text(self) -> str:
        return self._tentative_text

    def committed_text(self, sep: str = " ") -> str:
        return sep.join(s.text for s in self._committed if s.text)

    def update_tentative(self, segment_id: int, text: str) -> ReconcileResult:
        if segment_id in self._committed_ids:
            # Late/duplicate update for a segment that's already final.
            return ReconcileResult(emit=None, full_committed_text=self.committed_text())

        if self._open_segment_id is None:
            self._open_segment_id = segment_id
        elif self._open_segment_id != segment_id:
            # A new segment opened without an explicit commit of the old one
            # (e.g. provider VAD boundary). Treat the old tentative text as
            # abandoned (VAD false alarm / empty) rather than silently
            # committing something the engine never finalized.
            self._open_segment_id = segment_id
            self._tentative_text = ""

        self._tentative_text = text
        return ReconcileResult(
            emit={"kind": "tentative", "segment_id": segment_id, "text": text},
            full_committed_text=self.committed_text(),
        )

    def commit_segment(
        self,
        segment_id: int,
        text: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> ReconcileResult:
        if segment_id in self._committed_ids:
            return ReconcileResult(emit=None, full_committed_text=self.committed_text())

        self._committed_ids.add(segment_id)
        if text:
            self._committed.append(
                CommittedSegment(segment_id=segment_id, text=text, start_ms=start_ms, end_ms=end_ms)
            )
        if self._open_segment_id == segment_id:
            self._open_segment_id = None
            self._tentative_text = ""

        return ReconcileResult(
            emit={
                "kind": "committed",
                "segment_id": segment_id,
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
            },
            full_committed_text=self.committed_text(),
        )

    def discard_segment(self, segment_id: int) -> None:
        """Drop a tentative segment with no committed output (e.g. noise)."""
        if self._open_segment_id == segment_id:
            self._open_segment_id = None
            self._tentative_text = ""
        self._committed_ids.add(segment_id)
