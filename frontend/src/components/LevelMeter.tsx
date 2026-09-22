const MIN_DBFS = -60;
const MAX_DBFS = 0;

export function LevelMeter({ dbfs, active }: { dbfs: number; active: boolean }) {
  const clamped = Math.max(MIN_DBFS, Math.min(MAX_DBFS, dbfs));
  const pct = active ? ((clamped - MIN_DBFS) / (MAX_DBFS - MIN_DBFS)) * 100 : 0;
  return (
    <div className="level-meter" role="meter" aria-label="Microphone input level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <div className="level-meter__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
