import { ClientMessage, packAudioFrame, ServerMessage } from "../protocol";

const RECONNECT_DELAYS_MS = [1000, 2000, 4000];

export interface TranscriberClientOptions {
  url: string;
  language: string;
  vocabularyHints: string[];
  sampleRate: number;
  onServerMessage: (msg: ServerMessage) => void;
  onReconnecting: (attempt: number, max: number) => void;
  onReconnectFailed: () => void;
  onFatalClose: (reason: string) => void;
}

/**
 * Owns the single WebSocket for one recording. Reconnects with limited
 * retries + backoff on an *unexpected* drop while actively
 * recording/paused; a reconnect always starts a brand new backend session
 * (our in-memory session store cannot safely resume mid-utterance
 * recognition state -- see README "Connection reliability"), so the caller
 * is expected to mark a gap in the transcript when session_id changes.
 */
export class TranscriberClient {
  private ws: WebSocket | null = null;
  private seq = 0;
  private intentionalClose = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private wasRecording = false;

  constructor(private options: TranscriberClientOptions) {}

  connect(): void {
    this.intentionalClose = false;
    this._open();
  }

  private _open(): void {
    const ws = new WebSocket(this.options.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    ws.onopen = () => {
      this.wasRecording = true;
      this.reconnectAttempt = 0;
      this.seq = 0;
      const start: ClientMessage = {
        type: "session_start",
        sample_rate: this.options.sampleRate,
        channels: 1,
        language: this.options.language,
        vocabulary_hints: this.options.vocabularyHints,
      };
      ws.send(JSON.stringify(start));
    };

    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== "string") return; // server never sends binary
      try {
        const msg = JSON.parse(event.data) as ServerMessage;
        this.options.onServerMessage(msg);
      } catch {
        // Malformed server message: ignore rather than crash the session.
      }
    };

    ws.onclose = () => {
      if (this.intentionalClose || !this.wasRecording) return;
      this._attemptReconnect();
    };

    ws.onerror = () => {
      // onclose always follows onerror for WebSocket; reconnect is handled there.
    };
  }

  private _attemptReconnect(): void {
    if (this.reconnectAttempt >= RECONNECT_DELAYS_MS.length) {
      this.options.onReconnectFailed();
      return;
    }
    const delay = RECONNECT_DELAYS_MS[this.reconnectAttempt];
    this.reconnectAttempt += 1;
    this.options.onReconnecting(this.reconnectAttempt, RECONNECT_DELAYS_MS.length);
    this.reconnectTimer = setTimeout(() => this._open(), delay);
  }

  sendAudioFrame(pcm: Int16Array): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    const frame = packAudioFrame(this.seq, pcm);
    this.seq += 1;
    this.ws.send(frame);
  }

  private sendControl(msg: ClientMessage): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(msg));
  }

  pause(): void {
    this.sendControl({ type: "pause" });
  }

  resume(): void {
    this.sendControl({ type: "resume" });
  }

  stop(): void {
    this.wasRecording = false; // a server-initiated close after Stop is expected, not a failure
    this.sendControl({ type: "stop" });
  }

  /** Hard close, e.g. unmount or Clear session -- no reconnect attempted. */
  close(): void {
    this.intentionalClose = true;
    this.wasRecording = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close(1000, "client closed");
    this.ws = null;
  }
}
