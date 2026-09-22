import { useState } from "react";

export interface ActionsProps {
  transcriptText: string;
  canClear: boolean;
  onClear: () => void;
}

function downloadTxt(text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  a.href = url;
  a.download = `live-transcriber-${timestamp}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function Actions(props: ActionsProps) {
  const [copyLabel, setCopyLabel] = useState("Copy");
  const hasText = props.transcriptText.trim().length > 0;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(props.transcriptText);
      setCopyLabel("Copied ✓");
      setTimeout(() => setCopyLabel("Copy"), 1500);
    } catch {
      setCopyLabel("Copy failed");
      setTimeout(() => setCopyLabel("Copy"), 1500);
    }
  };

  return (
    <div className="actions">
      <button type="button" className="btn" onClick={handleCopy} disabled={!hasText}>
        {copyLabel}
      </button>
      <button type="button" className="btn" onClick={() => downloadTxt(props.transcriptText)} disabled={!hasText}>
        Download .txt
      </button>
      <button type="button" className="btn btn--subtle" onClick={props.onClear} disabled={!props.canClear}>
        Clear session
      </button>
    </div>
  );
}
