import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { LibraryItem } from "../lib/types";

const TIER_LABELS: Record<number, string> = {
  0: "MP3 128",
  1: "MP3 320",
  2: "FLAC 16/44.1",
  3: "Hi-Res 24/96",
  4: "Hi-Res 24/192",
};

const fmtDate = (s?: string | null): string => {
  if (!s) return "";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
};

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () =>
    api
      .libraryItems()
      .then(setItems)
      .catch((e) => setError((e as Error).message));
  useEffect(() => void load(), []);

  const rescan = async () => {
    try {
      await api.rescan();
      setMsg("Reescaneo de Navidrome solicitado.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Biblioteca</h1>
        <button className="btn-ghost px-2 py-1 text-xs" onClick={rescan}>
          Reescanear Navidrome
        </button>
      </div>
      <p className="text-sm text-slate-400">
        Lo que esta app ha descargado, con su calidad. Lo que esté en mejor calidad disponible se
        puede re-descargar desde el buscador.
      </p>

      {msg && (
        <div className="rounded-md border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm">
          {msg}
        </div>
      )}
      {error && <p className="text-red-400">{error}</p>}
      {items && items.length === 0 && (
        <p className="text-slate-500">Aún no has descargado nada.</p>
      )}

      {items && items.length > 0 && (
        <div className="card divide-y divide-slate-800 p-0">
          {items.map((it) => (
            <div key={it.id} className="flex items-center justify-between gap-3 px-4 py-2">
              <div className="min-w-0">
                <div className="truncate font-medium">{it.title}</div>
                <div className="truncate text-sm text-slate-400">
                  {it.artist}
                  {it.album ? ` · ${it.album}` : ""}
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-0.5 text-xs text-slate-400">
                <span className="chip border border-slate-700">
                  {TIER_LABELS[it.quality_tier] ?? `tier ${it.quality_tier}`}
                  {it.bitrate_kbps ? ` · ${it.bitrate_kbps}k` : ""}
                </span>
                <span className="text-slate-500">
                  {it.source_provider}
                  {fmtDate(it.downloaded_at) ? ` · ${fmtDate(it.downloaded_at)}` : ""}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
