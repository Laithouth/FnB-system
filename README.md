# Live Transcriber

Real-time speech-to-text: click **Start**, speak, watch your words appear as you talk. Click
**Stop** and get an editable, copyable, downloadable transcript. Self-hosted — your audio is
processed on a server you control, never sent to a third-party cloud API.

This README documents what was actually built and verified, what wasn't verified and why, and
exactly how to run it yourself. Where a claim can't be backed by something that ran in this
project's development environment, it's labeled **unverified** with exact steps to verify it
yourself.

## 1. TL;DR

```bash
# Terminal 1 — backend (default provider is faster-whisper; needs Hugging
# Face access on first run — see section 2. No GPU/HF access handy?
# `echo "PROVIDER=pocketsphinx" >> backend/.env` first for an offline dev loop.)
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`, click **Start**, allow microphone access, speak. See section 4 for
full setup detail, HTTPS requirements, and troubleshooting.

## 2. Model choice: why not R2T2, and what runs instead

The spec asked for R2T2 (Confucius4-R2T2, NetEase Youdao) to be evaluated first. It was — against
the model's own repository and model card (`github.com/netease-youdao/Confucius4-R2T2`,
`huggingface.co/netease-youdao/Confucius4-R2T2`) — before choosing an engine.

**What R2T2 actually is:** a low-latency streaming ASR model built on the Qwen3-ASR architecture,
served over a WebSocket API (`/asr_stream_api_v1`) that takes raw 16kHz mono PCM16 and returns
append-only incremental text. Its own inference stack requires vLLM or Hugging Face
`transformers`, and its docs state an **NVIDIA GPU is required** (vLLM has strict CUDA/PyTorch
version requirements). Source code is Apache 2.0; model weights are under NetEase's own,
separate "Model Use License Agreement" — a more restrictive license than the code.

**Why it can't run here:** this project's development sandbox has no GPU (`nvidia-smi` is not
present) and its network egress policy blocks `huggingface.co` outright (`CONNECT` returns 403),
which is where R2T2's weights live. Both conditions were checked directly, not assumed. Even with
GPU + network access, R2T2's weights carry a distinct usage license from its Apache-2.0 code —
read NetEase's Model Use License Agreement yourself on the model card before deploying it.

**What runs instead, and why:**

| Provider | Runs in this sandbox? | Accuracy | License | Needs |
|---|---|---|---|---|
| **faster-whisper** (default) | ⚠️ unverified here | Materially better — needed to catch order vocabulary reliably | MIT | Hugging Face access on first run; GPU optional |
| **pocketsphinx** (this project's test-suite provider) | ✅ verified | Low (classical HMM/GMM, ~15 yrs old) | BSD | Nothing — model ships in the pip wheel |
| R2T2 | ❌ can't run here | Unknown (not tested) | Apache-2.0 code / separate weight license | GPU + Hugging Face access |

Both real providers implement the exact same `TranscriptionProvider` interface
(`backend/app/providers/base.py`), so switching is one environment variable (`PROVIDER=...`), not
a rewrite — this is the "replaceable transcription-provider interface" the spec asked for. An R2T2
adapter could be written against the same interface once a GPU + Hugging Face access are available;
it was not written speculatively here because it could not be tested.

**Why the default is faster-whisper despite being unverified here**: this app is meant to feed a
drive-thru voice-ordering system, where recognizing menu items, sizes, and modifiers correctly
matters far more than in general dictation — pocketsphinx has no vocabulary-hint support at all,
and its classical acoustic model is a poor fit for that. faster-whisper does support vocabulary
hints (section "Order vocabulary hints" below) and is the shipped default for that reason, even
though this sandbox can't verify it end-to-end (see immediately below). Running it here does
prove the failure is exactly the expected one and nothing else — `python3 -c "import app.main"`
with `PROVIDER=faster_whisper` fails with `httpx.ProxyError: 403 Forbidden` while
`huggingface_hub` tries to fetch model info, i.e. the egress block, not a bug in the provider code.

**pocketsphinx was verified**, end to end, three separate ways documented in section 5: a direct
unit-level streaming test, a live WebSocket session test over a real TCP socket, and a real headless
browser (Chromium, with a real WAV fed through its fake-microphone device) driving the actual
web UI. It remains what this project's own automated test suite runs against
(`tests/conftest.py` pins `PROVIDER=pocketsphinx` regardless of the app's real default) precisely
because it's the only engine that can be verified offline. **faster-whisper's code is real and
complete** (`backend/app/providers/faster_whisper_provider.py`) but has not been run to
completion in this environment — do that yourself per section 5.4 before relying on it.

### Order vocabulary hints

Since this feeds a voice-ordering system, every session applies a small built-in set of generic
drive-thru/QSR terms (sizes, combo/upsize language, common modifiers — see
`app/config.py:default_vocabulary_hints`) as a hint to the engine, unioned with whatever
restaurant-specific hints the client sends (the Settings panel's vocabulary field, or
`session_start.vocabulary_hints` in the protocol directly). Only providers with
`supports_hints=True` actually use them — that's faster-whisper (via Whisper's `initial_prompt`,
a soft nudge, not a hard constraint) today; pocketsphinx ignores them entirely (logged, not
silently dropped — see `PocketSphinxSession.__init__`). Override the generic defaults with a real
menu via `DEFAULT_VOCABULARY_HINTS` in `.env` (comma-separated). The merge logic itself
(`app/config.py:merge_vocabulary_hints`) is unit-tested (`tests/test_config.py`) independent of
which provider is active. **Whether hints measurably improve recognition of real menu terms is
unverified** — faster-whisper hasn't run end-to-end here at all (see above); verify with your own
menu and real speech per section 5.5.

## 3. Architecture

```
Browser                                    Backend (FastAPI)
┌─────────────────────────┐   WebSocket    ┌────────────────────────────┐
│ getUserMedia             │◄──────────────►│ /ws/transcribe             │
│  → AudioWorklet          │  JSON control   │  receiver → work queue     │
│    (downmix, resample,   │  + binary PCM   │  processor → provider     │
│     PCM16 framing)       │  frames         │  sender → outbound queue  │
│  → WebSocket client      │                 │                            │
│    (reconnect/backoff)   │                 │  TranscriptionProvider     │
│  → transcript reducer    │                 │   ├─ FasterWhisperProvider │
│  → React UI              │                 │   └─ PocketSphinxProvider  │
└─────────────────────────┘                 └────────────────────────────┘
```

- **Frontend**: React + TypeScript + Vite. `src/audio/capture.ts` owns `getUserMedia`/`AudioContext`;
  `public/audio-worklet-processor.js` does downmixing, linear resampling to 16kHz, and PCM16
  framing entirely off the main thread. `src/ws/client.ts` owns the WebSocket and reconnect
  logic. `src/state/transcript.ts` is a pure reducer mirroring the backend's reconciliation rules
  (defense in depth against reordering/duplication across a reconnect).
- **Backend**: FastAPI. One WebSocket connection = one session (`app/session.py`) — this is what
  makes session isolation structural: nothing is shared mutable state across connections except
  the read-only provider factory. Three asyncio tasks per connection (receiver / processor /
  sender) so the one non-thread-safe decoder is only ever touched from a single task, and control
  commands (pause/stop) go through the *same* ordered queue as audio so a Stop can't jump ahead of
  unprocessed audio.
- **Protocol** (`backend/app/protocol.py`, mirrored in `frontend/src/protocol.ts`): JSON control
  messages + binary audio frames (an 8-byte seq/frame-type header + raw PCM16). Session ids are
  server-generated; segment ids and per-event seq numbers let both sides detect stale/duplicate/
  out-of-order events.
- **Reconciliation** (`backend/app/reconciler.py`, mirrored in `frontend/src/state/transcript.ts`):
  committed segments are immutable once emitted; a segment's tentative hypothesis is *replaced*,
  never appended, as the engine's cumulative partial result grows; legitimate repeats ("very, very
  important") are preserved because de-duplication is keyed on segment id, never on text content.

## 4. Setup

### 4.1 Backend

Requires Python 3.11+.

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # includes faster-whisper + pocketsphinx
cp .env.example .env   # adjust if needed
uvicorn app.main:app --reload --port 8000
```

The default provider is faster-whisper, which downloads model weights from Hugging Face on first
run — needs real network access to `huggingface.co` (see section 2 for why that's unverified in
this project's own sandbox). If you don't have that handy yet, switch to the fully offline
provider for local dev:

```bash
echo "PROVIDER=pocketsphinx" >> .env
uvicorn app.main:app --reload --port 8000
```

Verify it's actually ready (not just "the process started"):

```bash
curl http://localhost:8000/readyz
# {"ready":true,"provider":"faster_whisper","model":"faster-whisper (small)","active_sessions":0,...}
# (or provider":"pocketsphinx" if you switched above)
```

### 4.2 Frontend

Requires Node 18+.

```bash
cd frontend
npm install
cp .env.example .env.local   # VITE_BACKEND_WS_URL, defaults to ws://localhost:8000/...
npm run dev
```

Open `http://localhost:5173`.

**HTTPS/localhost requirement**: browsers only allow microphone access (`getUserMedia`) on
`localhost`/`127.0.0.1` or a page served over HTTPS — this is a browser platform requirement, not
something this app can work around. `npm run dev` on `localhost` satisfies this for local
development. For any non-localhost deployment, put the frontend behind TLS (a reverse proxy like
Caddy/Nginx with a real certificate, or a static host that provides HTTPS) — the level meter,
mic selector, and recording will silently fail to start (`getUserMedia` throws) on plain HTTP
elsewhere.

**Browser support**: needs `getUserMedia` + `AudioWorklet` + `WebSocket` — current Chrome, Edge,
Firefox, and Safari all support these (per MDN compatibility data). Only actually exercised in
this project on Chromium (see section 5); Firefox/Safari are **unverified** — the code uses only
standard APIs with no Chromium-specific behavior, but confirm yourself before relying on it.

### 4.3 Docker

`docker-compose.yml` builds both services. **Unverified**: this project's sandbox has no Docker
daemon available (`docker info` can't reach `/var/run/docker.sock`), so the compose file itself
was never built or run — only the underlying `pip install`/`npm install`/`npm run build` steps it
executes were, directly, and confirmed working (section 5). Verify with:

```bash
docker compose up --build
# backend on :8000, frontend on :5173
```

## 5. Testing — what was verified, and how

### 5.1 Backend unit/integration tests (automated, all passing)

```bash
cd backend && python3 -m pytest -q
# 38 passed
```

`tests/conftest.py` sets `PROVIDER=pocketsphinx` before anything else imports, so this suite runs
fully offline regardless of the app's real default (faster-whisper) — see section 2.

Covers: audio frame packing/unpacking, resampling, downmixing, RMS level math
(`test_audio.py`); order-vocabulary hint merging — union not replace, case-insensitive dedup,
`DEFAULT_VOCABULARY_HINTS` env override (`test_config.py`); the reconciliation state machine —
replace-not-append, immutable commits, dedup by id not text, legitimate-repeat preservation
(`test_reconciler.py`); full WebSocket session lifecycle including the reject-without-session_start
path, malformed-message handling, and pause/resume timeline preservation, run against the *real*
FastAPI app + real pocketsphinx provider, not mocks (`test_session_lifecycle.py`); and **real
audio in, real text out** — synthesized (espeak-ng) speech streamed through the actual
`PocketSphinxSession` in 100ms chunks, asserting genuine incremental partial hypotheses and
non-empty committed output (`test_integration_pocketsphinx.py`).

### 5.2 Live server, real socket, real speech (manual, run and confirmed)

The fixture WAV (`backend/tests/fixtures/sample_speech_16k_mono.wav`, real synthesized speech —
see `generate_fixture.py`) was streamed to a **live, separately-running** `uvicorn` process over a
real TCP WebSocket connection (not FastAPI's in-process TestClient), using the exact wire protocol
the frontend uses. It produced real incremental transcript_events and a real committed final
transcript. This confirms the server works as an actual network service, not just importable code.

### 5.3 Real browser, real UI, real audio pipeline (manual, run and confirmed)

No physical microphone exists in this project's sandbox, so full manual verification with a human
voice is **unverified** here (see 5.5 for exact steps to do it yourself) — but the entire
browser-side pipeline was still verified in a **real Chromium engine** (Playwright-launched,
`/opt/pw-browsers`), using Chromium's `--use-file-for-fake-audio-capture` flag to feed the same
real speech WAV in as the "microphone" device. This exercises the actual `getUserMedia` →
`AudioWorklet` (real downmix/resample/PCM16 framing, off the main thread) → `WebSocket` → backend
→ `transcript_event` → React reducer → DOM pipeline, with no test-only code path — it's the same
build a person would run. Confirmed:

- Start → Requesting mic → Connecting → Listening state transitions.
- The level meter genuinely tracks input energy (0% on silence, ~60% on real speech — verified
  both ways).
- Real recognized words appear incrementally and reach the completed, editable transcript.
- **Pause freezes the recording timer; Resume continues it** — verified by reading the DOM timer
  value across a pause window (stayed at `00:01` through a 1.5s pause, then advanced after Resume).
- Stop → Finishing → Complete, with the transcript still present and editable.
- A `getUserMedia` failure (no device available) surfaces the mapped, human-readable error banner
  — confirmed live; the code additionally maps `NotAllowedError` (permission denied) and
  `NotReadableError` (device busy) the same way, but only the no-device path was actually
  triggered in this sandbox (there's no way to make headless Chromium *deny* a prompt without also
  having no device — see 5.5).
- Zero unexpected browser console errors (one cosmetic favicon 404 during testing, now fixed).

This is real evidence the plumbing works, from a real browser. It is **not** evidence of
recognition *accuracy* with human speech, or of behavior on a real physical microphone, a real
permission-denial dialog, real device unplug events, or non-Chromium browsers — see 5.5.

### 5.4 Explicitly unverified

- **faster-whisper provider**: real, complete code — and now the app's shipped default — but
  never run to completion in this sandbox (needs Hugging Face access this sandbox blocks). It was
  run far enough to confirm the failure is exactly the network block (`httpx.ProxyError: 403
  Forbidden` from `huggingface_hub`, section 2), not a code bug, but that's not the same as
  confirming it actually transcribes anything. Before relying on it: `pip install -r
  requirements.txt` (already includes it), run the app with network access to Hugging Face — first
  request downloads weights.
- **Whether order-vocabulary hints measurably help**: the merge logic is unit-tested, but nothing
  in this sandbox exercised faster-whisper's `initial_prompt` against real menu speech — see the
  "Order vocabulary hints" section above.
- **R2T2**: not run at all (see section 2).
- **Recognition accuracy with a real human voice**: everything above used synthesized (espeak-ng)
  speech. PocketSphinx's word-error rate on a real, clear, native-English voice will likely be
  *better* than what you saw in this project's test output (synthetic speech is harder for it),
  but this project makes no quantified WER claim either way — measure it yourself (5.5).
- **Latency numbers**: the product spec's targets (median <700ms, p95 <1.5s word-to-screen) were
  never measured against aligned reference timestamps — no claim is made that they're met. Casual
  observation during manual browser testing showed sub-second perceived responsiveness on this
  4-vCPU sandbox with pocketsphinx, but that is an impression, not a measurement — see 5.5 for how
  to measure it properly.
- **Firefox/Safari, real permission-denial UI, device-unplug-mid-recording, mobile layout on a
  physical phone, 20-30 minute long-session resource behavior, Arabic/French/Spanish recognition**
  (pocketsphinx doesn't support them at all — only faster-whisper's language list does, and that's
  itself unverified per above).

### 5.5 Exact steps to verify what's unverified, yourself

```bash
# 1. Real microphone, real voice, real browser (the big one):
cd backend && uvicorn app.main:app --port 8000 &
cd frontend && npm run dev
# open http://localhost:5173 in Chrome/Firefox/Safari, click Start, speak.

# 2. Real permission-denial dialog:
# click Start, then click "Block" in the browser's mic-permission prompt.
# Expect the "Microphone access was denied" banner.

# 3. Device unplug mid-recording:
# start recording, physically unplug/disable the mic. Expect "microphone
# was disconnected" and a clean stop (mic track .onended fires).

# 4. faster-whisper, end to end (default provider; requires HF network access):
# ensure PROVIDER=faster_whisper in backend/.env (the shipped default),
# restart uvicorn somewhere with real network access, repeat step 1.
# Compare accuracy against pocketsphinx (PROVIDER=pocketsphinx), and try
# the Settings panel's vocabulary field with real menu items.

# 5. Word-error rate: record yourself reading a known transcript, download
#    the app's output as .txt, diff against the reference with a WER tool
#    (e.g. `pip install jiwer` then `jiwer.wer(reference, hypothesis)`).

# 6. Latency: instrument with a clap/tone at a known timestamp in the
#    source audio and compare to the wall-clock time its transcript_event
#    arrives (browser DevTools Network tab shows WS frame timestamps).

# 7. Long-session resource use: record continuously for 20-30 minutes,
#    watch backend process RSS with `ps` or `docker stats`.
```

## 6. Performance targets (from the spec) vs. what's actually known

| Target | Status |
|---|---|
| Median word-to-screen latency < 700ms | Not measured with aligned timestamps. Not claimed. |
| p95 latency < 1.5s | Not measured. Not claimed. |
| Cold start vs. warm inference | Not measured. pocketsphinx's decoder loads its bundled ~27MB language model at session start (`PocketSphinxProvider.__init__` probes this once at process startup, and `/readyz` reflects it) — a rough sense of load time is visible in server logs, not formally benchmarked. |
| Stop → final transcript delay | Bounded by `FINALIZE_TIMEOUT_S` (default 8s) — a hard ceiling, not a measured typical value. |
| WER | Not measured against a human-checked reference corpus. See 5.5 step 5. |
| 20-30 min session resource behavior | Not measured. |

Every one of these is a real, runnable measurement someone can take with the steps in 5.5 — none
of them were fabricated as numbers here.

## 7. Data handling and privacy

- Audio is processed **on the backend server you run** (in-process pocketsphinx/faster-whisper
  inference) — never sent to a third-party cloud transcription API, with no silent cloud fallback
  anywhere in the code.
- Raw audio is **never written to disk**. It lives only in small in-memory buffers
  (`bytearray` frame buffers in the provider sessions) for the duration of active decoding, and is
  discarded once each utterance is finalized.
- Transcript text lives in memory for the session (server: the `TranscriptReconciler` instance;
  browser: React state) and is not persisted anywhere unless *you* click Download.
- No diagnostic logging includes audio or full transcript content — server logs only log
  operational events (session start/stop, errors, timeouts), never recognized text.
- The WebSocket endpoint has **no authentication by default** — appropriate only for local
  development. Set `REQUIRE_API_KEY=true` and a real `API_KEY` for anything internet-reachable,
  put it behind TLS, and set `ALLOWED_ORIGINS` to your real frontend origin (CORS/WS origin
  checking is already implemented in `app/main.py`).

## 8. Licensing and ongoing costs

- **This project's own code**: no license file was added beyond the repository's existing
  `LICENSE`; treat additions the same way.
- **pocketsphinx**: BSD-licensed, source + bundled model both.
- **faster-whisper**: MIT-licensed; the underlying Whisper model weights it downloads from Hugging
  Face are OpenAI's, MIT-licensed.
- **R2T2**: Apache-2.0 *source*; model *weights* under NetEase's own Model Use License Agreement —
  read it yourself on the model card before any use, since it is explicitly a different license
  than the code.

**Cost shape**: this is a self-hosted app, not a per-request paid API — there is no per-minute
transcription fee to any provider. The real ongoing cost is **compute to host the backend**:
either a small CPU instance (pocketsphinx, or faster-whisper with a small/int8 model) or a
GPU instance (faster-whisper with a larger model for better accuracy/throughput). This project
tried to cite current, specific cloud pricing here and could not: this sandbox's network egress
policy blocks both `aws.amazon.com` and `digitalocean.com` (confirmed — both return a proxy
403), so no live price was available to quote honestly. Check current pricing yourself before
budgeting:
- AWS EC2 on-demand pricing: `https://aws.amazon.com/ec2/pricing/on-demand/`
- Google Cloud Compute Engine pricing: `https://cloud.google.com/compute/all-pricing`
- A GPU instance is only needed if you choose faster-whisper with a larger model for higher
  throughput/accuracy; pocketsphinx and small faster-whisper models run on CPU.

## 9. Known limitations

- faster-whisper (the default) needs Hugging Face access on first run and meaningfully more
  compute than pocketsphinx; it has not been run to completion anywhere in this project (section
  5.4). If you can't give it network/GPU access yet, `PROVIDER=pocketsphinx` is the fallback —
  but pocketsphinx has materially worse accuracy than modern neural ASR (expect it to struggle
  outside clear, close-mic, standard American English), supports English only (only the en-us
  acoustic model ships in the pip wheel), and does not support vocabulary hints at all — it
  cannot use the order-vocabulary feature described in section 2.
- The built-in default order-vocabulary hints are a generic drive-thru/QSR starting point, not
  any real restaurant's menu — set `DEFAULT_VOCABULARY_HINTS` before relying on this for actual
  orders, and see the "Order vocabulary hints" note in section 2 on why this is unverified to
  actually help.
- faster-whisper's "streaming" is re-decoding a growing buffer on a VAD-bounded utterance, not a
  natively incremental decoder — see its module docstring for the latency/CPU trade-off this
  implies, and why a natively streaming model would do better in production.
- No punctuation beyond what the underlying engine itself produces — pocketsphinx effectively
  produces none; don't expect fully punctuated prose without the (not-yet-built) Cleanup pass.
- In-memory session state only — a backend restart drops all active sessions; no persistent
  history yet (explicitly out of scope for this version, matching the spec).
- No authentication by default (see section 7) — must be configured before any non-local
  deployment.

## 10. Next three improvements

1. **Cleanup pass** (spec section 9): a separate, explicitly-labeled "Clean text" action using an
   LLM to fix punctuation/capitalization/paragraphing on the *committed* transcript only — never
   touching the live path, never treating spoken content as instructions, never replacing the
   original. The interface point for this is intentionally already separated (`committedPlainText`
   in `frontend/src/state/transcript.ts`) so it can be added without touching the streaming path.
2. **Real WER/latency benchmarking harness**: a scripted version of section 5.5 steps 5-6 that
   runs against a small corpus of real recorded (not synthesized) reference audio with known
   transcripts, so accuracy/latency claims in this README stop being "go measure it yourself" and
   become numbers checked into the repo.
3. **faster-whisper run end-to-end, with a real menu**: it's the shipped default, but has not
   run anywhere with real Hugging Face/network access in this project. Run it somewhere that has
   that access, set `DEFAULT_VOCABULARY_HINTS` to an actual restaurant's menu, measure whether
   hints reduce menu-item recognition errors, and only then treat "faster-whisper + hints" as
   confirmed rather than just implemented. Add an R2T2 adapter behind the same
   `TranscriptionProvider` interface afterward if its GPU/licensing requirements are acceptable.

## 11. Project layout

```
backend/
  app/
    main.py           FastAPI app, WebSocket endpoint, health/readiness
    session.py         Per-connection session, work/outbound queues
    protocol.py         Wire protocol (pydantic models)
    reconciler.py        Tentative/committed transcript state machine
    audio.py               Frame packing, resample, downmix, RMS
    config.py                Environment-based settings
    providers/
      base.py                 TranscriptionProvider interface
      faster_whisper_provider.py  Default, production-grade, unverified here
      pocketsphinx_provider.py   Offline, verified, used by the test suite
  tests/                  38 automated tests (see section 5.1)
  requirements.txt
  Dockerfile
  .env.example
frontend/
  src/
    audio/capture.ts        getUserMedia + AudioWorklet orchestration
    ws/client.ts              WebSocket client, reconnect/backoff
    state/                       Transcript reducer, session hook
    components/                    UI components
    protocol.ts                     Wire protocol (TypeScript mirror)
  public/audio-worklet-processor.js   Downmix/resample/framing (audio thread)
  scripts/                              Manual browser E2E verification scripts
  Dockerfile
  .env.example
docker-compose.yml
```
