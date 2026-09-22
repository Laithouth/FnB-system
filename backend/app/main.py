"""FastAPI application: WebSocket streaming endpoint + health/readiness.

One WebSocket connection = one recording session (see session.py). Three
asyncio tasks cooperate per connection, all touching provider_session and
the socket from exactly one place each:

  - receiver  (this coroutine): reads the socket, enqueues audio frames and
    control commands onto the session's single ordered work queue.
  - processor (audio_processor_task): the *only* task that calls into
    provider_session; drains the work queue in order.
  - sender    (sender_task): the *only* task that calls websocket.send();
    drains the session's outbound message queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .audio import AudioFrameError, unpack_audio_frame
from .config import merge_vocabulary_hints, settings
from .protocol import ErrorMessage, ReadyMessage, StatusMessage, TranscriptEvent, parse_client_message
from .providers.base import TranscriptionProvider
from .providers.pocketsphinx_provider import PocketSphinxProvider
from .session import RecordingState, Session, SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_provider() -> TranscriptionProvider:
    if settings.provider == "pocketsphinx":
        return PocketSphinxProvider()
    if settings.provider == "faster_whisper":
        # Imported lazily: faster-whisper (and its ctranslate2 dependency)
        # is an optional extra, and importing it eagerly would break the
        # pocketsphinx-only default install. See providers/faster_whisper_provider.py
        # for why this path is unverified in the network-restricted dev sandbox.
        from .providers.faster_whisper_provider import FasterWhisperProvider

        return FasterWhisperProvider(
            model_size=settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    raise ValueError(f"Unknown PROVIDER={settings.provider!r}")


provider = _build_provider()
session_manager = SessionManager(provider)

app = FastAPI(title="Live Transcriber backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    """Liveness only: the process is up and serving HTTP."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness: the inference engine is actually loaded and can decode --
    not just that uvicorn started. A load balancer / orchestrator should
    gate traffic on this, not /healthz."""
    ready = provider.is_ready()
    body = {
        "ready": ready,
        "provider": provider.name,
        "model": provider.model_name(),
        "active_sessions": session_manager.active_count,
        "max_concurrent_sessions": settings.max_concurrent_sessions,
    }
    if not ready:
        from fastapi.responses import JSONResponse

        return JSONResponse(body, status_code=503)
    return body


def _origin_allowed(origin: str | None) -> bool:
    if not settings.allowed_origins or "*" in settings.allowed_origins:
        return True
    if origin is None:
        # Non-browser clients (tests, curl) don't send Origin; allow them --
        # browser-origin enforcement is what matters for CSRF-style abuse.
        return True
    return origin in settings.allowed_origins


def _check_api_key(websocket: WebSocket) -> bool:
    if not settings.require_api_key:
        return True
    key = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
    return key is not None and key == settings.api_key


async def audio_processor_task(session: Session) -> None:
    """The only task allowed to call into session.provider_session."""
    while True:
        item = await session.next_work_item()
        kind = item["kind"]

        if kind == "audio":
            if session.state != RecordingState.LISTENING:
                continue
            try:
                hyps = await asyncio.wait_for(
                    session.provider_session.feed_audio(item["payload"], settings.sample_rate),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning("session %s: provider timed out on a frame (overload)", session.session_id)
                session.send_nowait(
                    ErrorMessage(
                        code="inference_overload",
                        message="Transcription is falling behind; some audio may be delayed.",
                        recoverable=True,
                    ).model_dump()
                )
                continue
            for event in await session.apply_hypotheses(hyps):
                session.send_nowait(
                    TranscriptEvent(
                        session_id=session.session_id, seq=session.next_seq(), **event
                    ).model_dump()
                )

        elif kind == "pause":
            hyps = await session.provider_session.pause()
            for event in await session.apply_hypotheses(hyps):
                session.send_nowait(
                    TranscriptEvent(
                        session_id=session.session_id, seq=session.next_seq(), **event
                    ).model_dump()
                )
            session.state = RecordingState.PAUSED
            session.send_nowait(StatusMessage(state="paused").model_dump())

        elif kind == "resume":
            session.state = RecordingState.LISTENING
            session.send_nowait(StatusMessage(state="listening").model_dump())

        elif kind == "stop":
            session.state = RecordingState.FINISHING
            session.send_nowait(StatusMessage(state="finishing").model_dump())
            hyps = await session.provider_session.finalize(settings.finalize_timeout_s)
            for event in await session.apply_hypotheses(hyps):
                session.send_nowait(
                    TranscriptEvent(
                        session_id=session.session_id, seq=session.next_seq(), **event
                    ).model_dump()
                )
            session.state = RecordingState.COMPLETE
            session.send_nowait(StatusMessage(state="complete").model_dump())
            return  # processor's job is done; sender/receiver wind down too


async def sender_task(websocket: WebSocket, session: Session) -> None:
    """The only task allowed to call websocket.send()."""
    while True:
        message = await session.next_outbound()
        await websocket.send_text(json.dumps(message))
        if message.get("type") == "status" and message.get("state") == "complete":
            return


@app.websocket("/ws/transcribe")
async def ws_transcribe(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        await websocket.close(code=4403)
        return
    if not _check_api_key(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    if not session_manager.can_accept():
        await websocket.send_text(
            json.dumps(
                ErrorMessage(
                    code="server_busy",
                    message="Server is at capacity; please try again shortly.",
                    recoverable=True,
                ).model_dump()
            )
        )
        await websocket.close(code=1013)
        return

    await websocket.send_text(json.dumps(StatusMessage(state="connecting").model_dump()))

    # First message on every connection must be session_start.
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        start_msg = parse_client_message(json.loads(raw))
        if start_msg.type != "session_start":
            raise ValueError(f"expected session_start, got {start_msg.type!r}")
    except (asyncio.TimeoutError, ValueError, json.JSONDecodeError, WebSocketDisconnect) as exc:
        logger.info("rejecting connection: %s", exc)
        try:
            await websocket.send_text(
                json.dumps(
                    ErrorMessage(code="protocol_error", message=str(exc), recoverable=False).model_dump()
                )
            )
        except Exception:
            pass
        await websocket.close(code=4400)
        return

    if not provider.is_ready():
        await websocket.send_text(json.dumps(StatusMessage(state="loading_model").model_dump()))

    merged_hints = merge_vocabulary_hints(start_msg.vocabulary_hints, settings.default_vocabulary_hints)

    try:
        session = session_manager.create_session(
            language=start_msg.language,
            sample_rate=start_msg.sample_rate,
            vocabulary_hints=merged_hints,
        )
    except Exception as exc:  # e.g. unsupported language for this provider
        logger.exception("failed to start session")
        await websocket.send_text(
            json.dumps(ErrorMessage(code="model_error", message=str(exc), recoverable=False).model_dump())
        )
        await websocket.close(code=4422)
        return

    caps = provider.capabilities()
    await websocket.send_text(
        json.dumps(
            ReadyMessage(
                session_id=session.session_id,
                provider=provider.name,
                model=provider.model_name(),
                sample_rate=settings.sample_rate,
                supports_hints=caps.supports_hints,
                supports_confidence=caps.supports_confidence,
            ).model_dump()
        )
    )
    session.send_nowait(StatusMessage(state="listening").model_dump())

    processor = asyncio.create_task(audio_processor_task(session))
    sender = asyncio.create_task(sender_task(websocket, session))

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            data_bytes = message.get("bytes")
            data_text = message.get("text")

            if data_bytes is not None:
                if session.state not in (RecordingState.LISTENING,):
                    continue  # drop audio arriving while paused/finishing
                try:
                    _seq, _frame_type, payload = unpack_audio_frame(data_bytes)
                except AudioFrameError as exc:
                    session.send_nowait(
                        ErrorMessage(code="bad_audio_frame", message=str(exc)).model_dump()
                    )
                    continue
                if not session.enqueue_audio(payload):
                    dropped = session.dropped_frames
                    if dropped == 1 or dropped % 25 == 0:
                        session.send_nowait(
                            StatusMessage(
                                state="listening",
                                detail=(
                                    f"Audio buffer full; {dropped} frame(s) dropped. "
                                    "The server is falling behind -- check CPU load or network."
                                ),
                            ).model_dump()
                        )

            elif data_text is not None:
                try:
                    ctrl = parse_client_message(json.loads(data_text))
                except Exception as exc:
                    session.send_nowait(ErrorMessage(code="bad_message", message=str(exc)).model_dump())
                    continue

                if ctrl.type == "ping":
                    continue
                if ctrl.type == "session_start":
                    session.send_nowait(
                        ErrorMessage(
                            code="protocol_error",
                            message="session_start already sent for this connection",
                        ).model_dump()
                    )
                    continue

                await session.enqueue_control(ctrl.type)
                if ctrl.type == "stop":
                    # Wait for the processor to actually finish finalizing
                    # (bounded by settings.finalize_timeout_s inside
                    # provider_session.finalize) before tearing down.
                    await processor
                    await sender
                    break
    except WebSocketDisconnect:
        logger.info("session %s: client disconnected", session.session_id)
    except Exception:
        logger.exception("session %s: unhandled error", session.session_id)
    finally:
        for task in (processor, sender):
            if not task.done():
                task.cancel()
        await asyncio.gather(processor, sender, return_exceptions=True)
        session_manager.remove_session(session.session_id)
        try:
            await websocket.close()
        except Exception:
            pass
