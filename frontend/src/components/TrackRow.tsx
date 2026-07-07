import { useState } from "react";

import { api } from "../lib/api";
import { togglePreview, usePreview } from "../lib/preview";
import type { Job, TrackResult } from "../lib/types";
import { bestOption, flattenOptions, formatDuration, toTrackPayload } from "../lib/util";
import Artwork from "./Artwork";
import LibraryBadge from "./LibraryBadge";
import QualityBadge from "./QualityBadge";
import { useToast } from "./Toaster";

function PreviewButton({ track }: { track: TrackResult }) {
  const st = usePreview();
  const toast = useToast();
  const key = `${track.artist}|${track.title}|${track.album ?? ""}`;
  const active = st.key === key;
  const label = active && st.status === "loading" ? "…" : active && st.status === "playing" ? "⏸" : "▶";
  const onClick = () =>
    void togglePreview(key, async () => (await api.preview(track)).url).catch(() =>
      toast.error("No se pudo reproducir la vista previa."),
    );
  return (
    <button
      type="button"
      onClick={onClick}
      title="Escuchar el audio real antes de descargar"
      aria-label={active && st.status === "playing" ? "Pausar vista previa" : "Escuchar vista previa"}
      className={`shrink-0 rounded-full border border-slate-700 px-2 py-1 text-xs ${
        active ? "bg-brand text-slate-950" : "text-slate-300 hover:bg-slate-800"
      }`}
    >
      {label}
    </button>
  );
}

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
    <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 py-2">
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
      <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto">
        <PreviewButton track={track} />
        {options.length ? (
          <>
            <select
              className="input min-w-0 flex-1 py-1 sm:flex-none"
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
