import { AppState } from "../protocol";
import { LevelMeter } from "./LevelMeter";

function formatTimer(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

export interface ControlsProps {
  appState: AppState;
  levelDbfs: number;
  elapsedMs: number;
  micDevices: MediaDeviceInfo[];
  selectedDeviceId: string;
  onSelectDevice: (id: string) => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}

const BUSY_STATES: AppState[] = ["requesting_mic", "connecting", "loading_model", "reconnecting", "finishing"];

export function Controls(props: ControlsProps) {
  const { appState } = props;
  const isIdle = appState === "idle" || appState === "complete" || appState === "error";
  const isListening = appState === "listening";
  const isPaused = appState === "paused";
  const isBusy = BUSY_STATES.includes(appState);

  return (
    <section className="controls" aria-label="Recording controls">
      <div className="controls__row">
        <label className="mic-select">
          <span className="visually-hidden">Microphone</span>
          <select
            value={props.selectedDeviceId}
            onChange={(e) => props.onSelectDevice(e.target.value)}
            disabled={!isIdle}
          >
            <option value="">Default microphone</option>
            {props.micDevices.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || `Microphone ${d.deviceId.slice(0, 6)}`}
              </option>
            ))}
          </select>
        </label>

        <div className="controls__buttons">
          {isIdle && (
            <button type="button" className="btn btn--primary" onClick={props.onStart} disabled={isBusy}>
              Start
            </button>
          )}
          {isListening && (
            <>
              <button type="button" className="btn" onClick={props.onPause}>
                Pause
              </button>
              <button type="button" className="btn btn--danger" onClick={props.onStop}>
                Stop
              </button>
            </>
          )}
          {isPaused && (
            <>
              <button type="button" className="btn btn--primary" onClick={props.onResume}>
                Resume
              </button>
              <button type="button" className="btn btn--danger" onClick={props.onStop}>
                Stop
              </button>
            </>
          )}
          {isBusy && (
            <button type="button" className="btn" disabled>
              Working…
            </button>
          )}
        </div>

        <div className="controls__timer" aria-live="off">
          {formatTimer(props.elapsedMs)}
        </div>
      </div>

      <LevelMeter dbfs={props.levelDbfs} active={isListening} />
    </section>
  );
}
