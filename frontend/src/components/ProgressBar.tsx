export default function ProgressBar({
  pct,
  indeterminate,
}: {
  pct: number;
  indeterminate?: boolean;
}) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-slate-800">
      <div
        className={`h-full bg-brand transition-all ${indeterminate ? "w-1/3 animate-pulse" : ""}`}
        style={indeterminate ? undefined : { width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}
