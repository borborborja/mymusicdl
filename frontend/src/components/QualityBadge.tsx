import type { QualityOption } from "../lib/types";

export default function QualityBadge({ q }: { q: QualityOption }) {
  const cls = q.lossless
    ? "bg-emerald-500/15 text-emerald-300 border border-emerald-600/30"
    : "bg-slate-700/40 text-slate-300 border border-slate-600/40";
  return (
    <span className={`chip ${cls}`} title={q.note ?? undefined}>
      {q.label}
      {q.bitrate_kbps ? ` · ${q.bitrate_kbps}k` : ""}
    </span>
  );
}
