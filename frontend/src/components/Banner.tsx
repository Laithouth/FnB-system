export function Banner({
  kind,
  message,
  onDismiss,
}: {
  kind: "error" | "warning";
  message: string;
  onDismiss?: () => void;
}) {
  return (
    <div className={`banner banner--${kind}`} role="alert">
      <span>{message}</span>
      {onDismiss && (
        <button type="button" className="banner__dismiss" onClick={onDismiss} aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  );
}
