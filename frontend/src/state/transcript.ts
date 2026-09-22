import { TranscriptEventMessage } from "../protocol";

export interface CommittedItem {
  key: string;
  text: string;
  isGapMarker?: boolean;
}

export interface TranscriptState {
  committed: CommittedItem[];
  tentativeText: string;
  tentativeKey: string | null;
  currentSessionId: string | null;
}

export function createInitialTranscriptState(): TranscriptState {
  return { committed: [], tentativeText: "", tentativeKey: null, currentSessionId: null };
}

export type TranscriptAction =
  | { type: "SESSION_READY"; sessionId: string }
  | { type: "SERVER_EVENT"; event: TranscriptEventMessage }
  | { type: "RESET" };

/**
 * Client-side mirror of backend/app/reconciler.py's rules, applied to the
 * event *stream* rather than being the source of truth (the backend
 * already reconciled once) -- this is defense in depth against reordering,
 * duplication across a reconnect, or a late event from a session the UI
 * has already moved on from. See its docstring for the invariants.
 */
export function transcriptReducer(state: TranscriptState, action: TranscriptAction): TranscriptState {
  switch (action.type) {
    case "RESET":
      return createInitialTranscriptState();

    case "SESSION_READY": {
      const isReconnect = state.currentSessionId !== null && state.currentSessionId !== action.sessionId;
      const committed = isReconnect
        ? [
            ...state.committed,
            {
              key: `gap:${action.sessionId}`,
              text: "— reconnected after a dropped connection; a short gap may be missing —",
              isGapMarker: true,
            },
          ]
        : state.committed;
      return {
        committed,
        tentativeText: "",
        tentativeKey: null,
        currentSessionId: action.sessionId,
      };
    }

    case "SERVER_EVENT": {
      const ev = action.event;
      if (ev.session_id !== state.currentSessionId) {
        return state; // late event from a stale/previous session
      }
      const key = `${ev.session_id}:${ev.segment_id}`;
      const alreadyCommitted = state.committed.some((c) => c.key === key);

      if (ev.kind === "committed") {
        if (alreadyCommitted) return state; // duplicate commit, drop
        const clearingTentative = state.tentativeKey === key;
        return {
          ...state,
          committed: ev.text ? [...state.committed, { key, text: ev.text }] : state.committed,
          tentativeText: clearingTentative ? "" : state.tentativeText,
          tentativeKey: clearingTentative ? null : state.tentativeKey,
        };
      }

      // tentative
      if (alreadyCommitted) return state; // late tentative after its own commit
      return { ...state, tentativeText: ev.text, tentativeKey: key };
    }
  }
}

export function committedPlainText(state: TranscriptState): string {
  return state.committed
    .filter((c) => !c.isGapMarker)
    .map((c) => c.text)
    .join(" ");
}

export function fullPlainText(state: TranscriptState): string {
  const committed = committedPlainText(state);
  return [committed, state.tentativeText].filter(Boolean).join(" ").trim();
}
