/**
 * Mirrors backend/app/protocol.py. Keep these two files in sync by hand --
 * see that module's docstring for the full protocol description (segment
 * ids, seq numbers, binary audio frame header layout).
 */

export type AppState =
  | "idle"
  | "requesting_mic"
  | "connecting"
  | "loading_model"
  | "listening"
  | "paused"
  | "reconnecting"
  | "finishing"
  | "complete"
  | "error";

export interface SessionStartMessage {
  type: "session_start";
  sample_rate: number;
  channels: number;
  language: string;
  model?: string | null;
  vocabulary_hints: string[];
}

export interface PauseMessage {
  type: "pause";
}
export interface ResumeMessage {
  type: "resume";
}
export interface StopMessage {
  type: "stop";
}

export type ClientMessage = SessionStartMessage | PauseMessage | ResumeMessage | StopMessage;

export interface StatusMessage {
  type: "status";
  state: AppState;
  detail: string;
}

export interface ReadyMessage {
  type: "ready";
  session_id: string;
  provider: string;
  model: string;
  sample_rate: number;
  supports_hints: boolean;
  supports_confidence: boolean;
}

export interface TranscriptEventMessage {
  type: "transcript_event";
  session_id: string;
  segment_id: number;
  seq: number;
  kind: "tentative" | "committed";
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  confidence: number | null;
}

export interface ErrorServerMessage {
  type: "error";
  code: string;
  message: string;
  recoverable: boolean;
}

export type ServerMessage = StatusMessage | ReadyMessage | TranscriptEventMessage | ErrorServerMessage;

const AUDIO_HEADER_SIZE = 8;

export function packAudioFrame(seq: number, pcm: Int16Array, frameType = 0): ArrayBuffer {
  const out = new Uint8Array(AUDIO_HEADER_SIZE + pcm.byteLength);
  const view = new DataView(out.buffer);
  view.setUint32(0, seq >>> 0, true);
  view.setUint32(4, frameType >>> 0, true);
  out.set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength), AUDIO_HEADER_SIZE);
  return out.buffer;
}
