import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { AudioCapture } from "../audio/capture";
import { TranscriberClient } from "../ws/client";
import { AppState, ServerMessage } from "../protocol";
import {
  CommittedItem,
  createInitialTranscriptState,
  fullPlainText,
  transcriptReducer,
} from "./transcript";

const BACKEND_WS_URL = (import.meta.env.VITE_BACKEND_WS_URL as string | undefined) ?? "ws://localhost:8000/ws/transcribe";

function friendlyMicError(err: unknown): string {
  if (err instanceof DOMException) {
    switch (err.name) {
      case "NotAllowedError":
      case "PermissionDeniedError":
        return "Microphone access was denied. Allow microphone access in your browser's site settings and try again.";
      case "NotFoundError":
      case "DevicesNotFoundError":
        return "No microphone was found. Connect a microphone and try again.";
      case "NotReadableError":
      case "TrackStartError":
        return "The microphone is already in use by another application.";
      case "OverconstrainedError":
        return "The selected microphone is no longer available. Choose a different one.";
      default:
        return `Microphone error: ${err.message || err.name}`;
    }
  }
  return err instanceof Error ? err.message : "Unknown microphone error.";
}

export interface TranscriberSession {
  appState: AppState;
  errorMessage: string | null;
  warningMessage: string | null;
  levelDbfs: number;
  elapsedMs: number;
  transcriptText: string;
  committed: CommittedItem[];
  tentativeText: string;
  isEditable: boolean;
  editedText: string | null;
  micDevices: MediaDeviceInfo[];
  selectedDeviceId: string;
  language: string;
  vocabularyHints: string;
  supportsHints: boolean;
  providerLabel: string;
  start: () => void;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  clearSession: () => void;
  setEditedText: (text: string) => void;
  selectDevice: (deviceId: string) => void;
  setLanguage: (lang: string) => void;
  setVocabularyHints: (hints: string) => void;
  dismissWarning: () => void;
}

const TESTED_LANGUAGES = [{ code: "en", label: "English (tested)" }];
const EXPERIMENTAL_LANGUAGES = [
  { code: "ar", label: "Arabic (experimental — requires faster-whisper provider)" },
  { code: "fr", label: "French (experimental — requires faster-whisper provider)" },
  { code: "es", label: "Spanish (experimental — requires faster-whisper provider)" },
];
export const LANGUAGE_OPTIONS = [...TESTED_LANGUAGES, ...EXPERIMENTAL_LANGUAGES];

export function useTranscriberSession(): TranscriberSession {
  const [appState, setAppState] = useState<AppState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [warningMessage, setWarningMessage] = useState<string | null>(null);
  const [levelDbfs, setLevelDbfs] = useState(-120);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [micDevices, setMicDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [language, setLanguage] = useState("en");
  const [vocabularyHints, setVocabularyHints] = useState("");
  const [supportsHints, setSupportsHints] = useState(false);
  const [providerLabel, setProviderLabel] = useState("");
  const [editedText, setEditedTextState] = useState<string | null>(null);

  const [transcript, dispatch] = useReducer(transcriptReducer, undefined, createInitialTranscriptState);

  const captureRef = useRef<AudioCapture | null>(null);
  const clientRef = useRef<TranscriberClient | null>(null);
  const recordingStartedAtRef = useRef<number | null>(null);
  const pausedAccumRef = useRef(0);
  const pausedAtRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const appStateRef = useRef<AppState>("idle");
  appStateRef.current = appState;

  useEffect(() => {
    void AudioCapture.listInputDevices().then(setMicDevices);
    const refresh = () => void AudioCapture.listInputDevices().then(setMicDevices);
    navigator.mediaDevices?.addEventListener?.("devicechange", refresh);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", refresh);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const teardown = useCallback(() => {
    captureRef.current?.stop();
    captureRef.current = null;
    clientRef.current?.close();
    clientRef.current = null;
    stopTimer();
  }, [stopTimer]);

  useEffect(() => teardown, [teardown]); // release mic/socket on unmount

  const enterError = useCallback(
    (message: string) => {
      setErrorMessage(message);
      setAppState("error");
      teardown();
    },
    [teardown]
  );

  const handleServerMessage = useCallback((msg: ServerMessage) => {
    if (msg.type === "status") {
      setAppState(msg.state);
      if (msg.detail) setWarningMessage(msg.detail);
      if (msg.state === "complete") {
        captureRef.current?.stop();
        captureRef.current = null;
        stopTimer();
      }
    } else if (msg.type === "ready") {
      setSupportsHints(msg.supports_hints);
      setProviderLabel(`${msg.provider} — ${msg.model}`);
      dispatch({ type: "SESSION_READY", sessionId: msg.session_id });
      if (recordingStartedAtRef.current === null) {
        recordingStartedAtRef.current = performance.now();
      }
    } else if (msg.type === "transcript_event") {
      dispatch({ type: "SERVER_EVENT", event: msg });
    } else if (msg.type === "error") {
      if (msg.recoverable) {
        setWarningMessage(msg.message);
      } else {
        enterError(msg.message);
      }
    }
  }, [enterError, stopTimer]);

  const start = useCallback(() => {
    setErrorMessage(null);
    setWarningMessage(null);
    setEditedTextState(null);
    dispatch({ type: "RESET" });
    pausedAccumRef.current = 0;
    pausedAtRef.current = null;
    recordingStartedAtRef.current = null;
    setElapsedMs(0);
    setAppState("requesting_mic");

    const capture = new AudioCapture({
      onLevel: setLevelDbfs,
      onFrame: (pcm) => {
        if (appStateRef.current === "listening") {
          clientRef.current?.sendAudioFrame(pcm);
        }
      },
      onDeviceLost: () => enterError("The microphone was disconnected."),
      onError: (message) => setWarningMessage(message),
    });

    capture
      .start(selectedDeviceId || undefined)
      .then(() => {
        captureRef.current = capture;
        setAppState("connecting");
        const client = new TranscriberClient({
          url: BACKEND_WS_URL,
          language,
          vocabularyHints: vocabularyHints
            .split(",")
            .map((h) => h.trim())
            .filter(Boolean),
          sampleRate: capture.sampleRate,
          onServerMessage: handleServerMessage,
          onReconnecting: (attempt, max) => {
            setAppState("reconnecting");
            setWarningMessage(`Reconnecting (attempt ${attempt}/${max})…`);
          },
          onReconnectFailed: () => enterError("Lost connection to the server and could not reconnect."),
          onFatalClose: (reason) => enterError(reason),
        });
        clientRef.current = client;
        client.connect();

        timerRef.current = setInterval(() => {
          if (recordingStartedAtRef.current === null) return;
          const pausedExtra =
            pausedAtRef.current !== null ? performance.now() - pausedAtRef.current : 0;
          setElapsedMs(
            performance.now() -
              recordingStartedAtRef.current -
              pausedAccumRef.current -
              pausedExtra
          );
        }, 200);
      })
      .catch((err: unknown) => enterError(friendlyMicError(err)));
  }, [selectedDeviceId, language, vocabularyHints, handleServerMessage, enterError]);

  const pause = useCallback(() => {
    if (appStateRef.current !== "listening") return;
    pausedAtRef.current = performance.now();
    clientRef.current?.pause();
  }, []);

  const resume = useCallback(() => {
    if (appStateRef.current !== "paused") return;
    if (pausedAtRef.current !== null) {
      pausedAccumRef.current += performance.now() - pausedAtRef.current;
      pausedAtRef.current = null;
    }
    clientRef.current?.resume();
  }, []);

  const stop = useCallback(() => {
    if (appStateRef.current !== "listening" && appStateRef.current !== "paused") return;
    stopTimer();
    clientRef.current?.stop();
  }, [stopTimer]);

  const clearSession = useCallback(() => {
    teardown();
    dispatch({ type: "RESET" });
    setAppState("idle");
    setErrorMessage(null);
    setWarningMessage(null);
    setEditedTextState(null);
    setElapsedMs(0);
  }, [teardown]);

  const transcriptText = editedText ?? fullPlainText(transcript);
  const isEditable = appState === "complete" || appState === "error";

  return {
    appState,
    errorMessage,
    warningMessage,
    levelDbfs,
    elapsedMs,
    transcriptText,
    committed: transcript.committed,
    tentativeText: transcript.tentativeText,
    isEditable,
    editedText,
    micDevices,
    selectedDeviceId,
    language,
    vocabularyHints,
    supportsHints,
    providerLabel,
    start,
    pause,
    resume,
    stop,
    clearSession,
    setEditedText: setEditedTextState,
    selectDevice: setSelectedDeviceId,
    setLanguage,
    setVocabularyHints,
    dismissWarning: () => setWarningMessage(null),
  };
}
