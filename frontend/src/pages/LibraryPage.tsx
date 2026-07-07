import { useEffect, useMemo, useState } from "react";

import { useToast } from "../components/Toaster";
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

type Sort = "recent" | "quality" | "artist";

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();

  const load = () =>
    api
      .libraryItems()
      .then(setItems)
      .catch((e) => setError((e as Error).message));
  useEffect(() => void load(), []);

  const rescan = async () => {
    try {
      await api.rescan();
      toast.success("Reescaneo de Navidrome solicitado.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const redownload = async (it: LibraryItem) => {
    setBusy(it.id);
    try {
      // Re-queue via the same source provider; the free downloaders resolve by name.
      await api.enqueue([
        {
          provider: it.source_provider,
          quality: it.quality_tier,
          track: { title: it.title, artist: it.artist, album: it.album ?? null },
        },
      ]);
      toast.success(`En cola de nuevo: ${it.artist} — ${it.title}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const shown = useMemo(() => {
    if (!items) return items;
    const needle = q.trim().toLowerCase();
    let out = needle
      ? items.filter((it) =>
          `${it.title} ${it.artist} ${it.album ?? ""}`.toLowerCase().includes(needle),
        )
      : items.slice();
    out = out.sort((a, b) => {
      if (sort === "quality") return b.quality_tier - a.quality_tier;
      if (sort === "artist")
        return `${a.artist} ${a.title}`.localeCompare(`${b.artist} ${b.title}`);
      return (b.downloaded_at ?? "").localeCompare(a.downloaded_at ?? "");
    });
    return out;
  }, [items, q, sort]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Biblioteca</h1>
        <button className="btn-ghost px-2 py-1 text-xs" onClick={rescan}>
          Reescanear Navidrome
        </button>
      </div>
      <p className="text-sm text-slate-400">
        Lo que esta app ha descargado, con su calidad. Vuelve a descargar una pista si el archivo
        falló o quieres refrescarlo.
      </p>

      {items && items.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="input min-w-0 flex-1 basis-48"
            placeholder="Filtrar por título, artista o álbum…"
            aria-label="Filtrar biblioteca"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <label className="flex items-center gap-1.5 text-sm text-slate-400">
            Ordenar
            <select
              className="input py-1"
              value={sort}
              onChange={(e) => setSort(e.target.value as Sort)}
            >
              <option value="recent">Recientes</option>
              <option value="quality">Calidad</option>
              <option value="artist">Artista</option>
            </select>
          </label>
        </div>
      )}

      {error && <p className="text-red-400">{error}</p>}
      {items && items.length === 0 && (
        <p className="text-slate-500">Aún no has descargado nada.</p>
      )}
      {shown && items && items.length > 0 && shown.length === 0 && (
        <p className="text-slate-500">Nada coincide con «{q}».</p>
      )}

      {shown && shown.length > 0 && (
        <div className="card divide-y divide-slate-800 p-0">
          {shown.map((it) => (
            <div key={it.id} className="flex items-center justify-between gap-3 px-4 py-2">
              <div className="min-w-0">
                <div className="truncate font-medium">{it.title}</div>
                <div className="truncate text-sm text-slate-400">
                  {it.artist}
                  {it.album ? ` · ${it.album}` : ""}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <div className="flex flex-col items-end gap-0.5 text-xs text-slate-400">
                  <span className="chip border border-slate-700">
                    {TIER_LABELS[it.quality_tier] ?? `tier ${it.quality_tier}`}
                    {it.bitrate_kbps ? ` · ${it.bitrate_kbps}k` : ""}
                  </span>
                  <span className="text-slate-500">
                    {it.source_provider}
                    {fmtDate(it.downloaded_at) ? ` · ${fmtDate(it.downloaded_at)}` : ""}
                  </span>
                </div>
                <button
                  className="btn-ghost px-2 py-1 text-xs"
                  disabled={busy === it.id}
                  title="Volver a descargar esta pista"
                  onClick={() => redownload(it)}
                >
                  {busy === it.id ? "…" : "↓ Re-descargar"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
