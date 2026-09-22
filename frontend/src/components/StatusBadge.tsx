import { AppState } from "../protocol";

const LABELS: Record<AppState, string> = {
  idle: "Ready",
  requesting_mic: "Requesting microphone…",
  connecting: "Connecting…",
  loading_model: "Loading model…",
  listening: "Listening",
  paused: "Paused",
  reconnecting: "Reconnecting…",
  finishing: "Finishing…",
  complete: "Complete",
  error: "Error",
};

const TONE: Record<AppState, "neutral" | "active" | "warn" | "error"> = {
  idle: "neutral",
  requesting_mic: "warn",
  connecting: "warn",
  loading_model: "warn",
  listening: "active",
  paused: "warn",
  reconnecting: "warn",
  finishing: "warn",
  complete: "neutral",
  error: "error",
};

export function StatusBadge({ state }: { state: AppState }) {
  return (
    <span className={`status-badge status-badge--${TONE[state]}`}>
      <span className="status-dot" aria-hidden="true" />
      {LABELS[state]}
    </span>
  );
}
