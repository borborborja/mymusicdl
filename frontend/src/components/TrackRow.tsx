import { useState } from "react";

import { api } from "../lib/api";
import type { Job, TrackResult } from "../lib/types";
import { bestOption, flattenOptions, formatDuration, toTrackPayload } from "../lib/util";
import Artwork from "./Artwork";
import LibraryBadge from "./LibraryBadge";
import QualityBadge from "./QualityBadge";

export default function TrackRow({
  track,
  selectable,
  selected,
  onToggleSelected,
  onEnqueued,
}: {
  track: TrackResult;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelected?: () => void;
  onEnqueued?: (jobs: Job[]) => void;
}) {
  const options = flattenOptions(track);
  const [value, setValue] = useState(() => bestOption(track)?.value ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const download = async () => {
    const opt = options.find((o) => o.value === value);
    if (!opt) return;
    setBusy(true);
    setErr(null);
    try {
      const jobs = await api.enqueue([
        { provider: opt.provider, quality: opt.tier, track: toTrackPayload(track) },
      ]);
      onEnqueued?.(jobs);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-3 border-b border-slate-800 py-2">
      {selectable && (
        <input
          type="checkbox"
          checked={!!selected}
          onChange={onToggleSelected}
          className="h-4 w-4 shrink-0 accent-brand"
        />
      )}
      <Artwork
        src={track.cover_url}
        alt={track.album ?? track.title}
        seed={`${track.album ?? track.title} ${track.artist}`}
        rounded="rounded"
        className="h-11 w-11"
      />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{track.title}</div>
        <div className="truncate text-sm text-slate-400">
          {track.artist}
          {track.album ? ` · ${track.album}` : ""}
          {track.duration_s ? ` · ${formatDuration(track.duration_s)}` : ""}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {track.providers.flatMap((p) =>
            p.qualities.slice(0, 1).map((q) => <QualityBadge key={`${p.provider}:${q.tier}`} q={q} />),
          )}
          <LibraryBadge library={track.library} />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {options.length ? (
          <>
            <select
              className="input py-1"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            >
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button className="btn-primary" disabled={busy} onClick={download}>
              {busy ? "…" : "Descargar"}
            </button>
          </>
        ) : (
          <span className="text-xs text-slate-500">Sin fuentes</span>
        )}
      </div>
      {err && <span className="shrink-0 text-xs text-red-400">{err}</span>}
    </div>
  );
}
