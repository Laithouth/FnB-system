import { useEffect, useRef, useState } from "react";
import { CommittedItem } from "../state/transcript";

export interface TranscriptViewProps {
  committed: CommittedItem[];
  tentativeText: string;
  isEditable: boolean;
  /** Resolved text to show once editable: the user's edits if any exist,
   * otherwise the recognized transcript -- never blank just because the
   * user hasn't typed anything yet. */
  editableValue: string;
  onEdit: (text: string) => void;
}

const SCROLL_BOTTOM_THRESHOLD_PX = 48;

export function TranscriptView(props: TranscriptViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [isPinnedToBottom, setPinnedToBottom] = useState(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setPinnedToBottom(distanceFromBottom < SCROLL_BOTTOM_THRESHOLD_PX);
  };

  useEffect(() => {
    if (!isPinnedToBottom) return;
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [props.committed, props.tentativeText, isPinnedToBottom]);

  const jumpToLatest = () => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setPinnedToBottom(true);
  };

  if (props.isEditable) {
    return (
      <div className="transcript-view transcript-view--editing">
        <textarea
          className="transcript-editor"
          value={props.editableValue}
          onChange={(e) => props.onEdit(e.target.value)}
          aria-label="Transcript (editable)"
          spellCheck
        />
      </div>
    );
  }

  const hasContent = props.committed.length > 0 || props.tentativeText.length > 0;

  return (
    <div className="transcript-view">
      <div
        className="transcript-scroll"
        ref={containerRef}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        aria-label="Live transcript"
      >
        {!hasContent && <p className="transcript-placeholder">Click Start and begin speaking — your words will appear here.</p>}
        {props.committed.map((item) =>
          item.isGapMarker ? (
            <p key={item.key} className="transcript-gap">
              {item.text}
            </p>
          ) : (
            <span key={item.key} className="transcript-committed">
              {item.text}{" "}
            </span>
          )
        )}
        {props.tentativeText && <span className="transcript-tentative">{props.tentativeText}</span>}
      </div>
      {!isPinnedToBottom && (
        <button type="button" className="btn btn--jump" onClick={jumpToLatest}>
          Jump to latest ↓
        </button>
      )}
    </div>
  );
}
