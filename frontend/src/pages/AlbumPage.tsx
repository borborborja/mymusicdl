import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import Artwork from "../components/Artwork";
import TrackRow from "../components/TrackRow";
import { api } from "../lib/api";
import type { AlbumDetail, DownloadItemInput } from "../lib/types";
import { bestOption, flattenOptions, toTrackPayload } from "../lib/util";

const TIER_LABELS: Record<number, string> = {
  0: "MP3 128",
  1: "MP3 320",
  2: "FLAC 16/44.1",
  3: "Hi-Res 24/96",
  4: "Hi-Res 24/192",
};

export default function AlbumPage() {
  const { provider = "", id = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<AlbumDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [batchProvider, setBatchProvider] = useState("");
  const [batchTier, setBatchTier] = useState(1);
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setLoading(true);
    api
      .album(provider, id)
      .then(setDetail)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [provider, id]);

  const providersAvail = useMemo(() => {
    const m = new Map<string, string>();
    detail?.tracks.forEach((t) => t.providers.forEach((p) => m.set(p.provider, p.label)));
    return Array.from(m, ([idv, label]) => ({ id: idv, label }));
  }, [detail]);

  const tiersAvail = useMemo(() => {
    const s = new Set<number>();
    detail?.tracks.forEach((t) => t.providers.forEach((p) => p.qualities.forEach((q) => s.add(q.tier))));
    return Array.from(s).sort((a, b) => a - b);
  }, [detail]);

  useEffect(() => {
    if (providersAvail.length && !batchProvider) setBatchProvider(providersAvail[0].id);
  }, [providersAvail, batchProvider]);
  useEffect(() => {
    if (tiersAvail.length) setBatchTier(tiersAvail[tiersAvail.length - 1]);
  }, [tiersAvail]);

  const toggle = (i: number) =>
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });
  const toggleAll = () =>
    setSelected((prev) =>
      prev.size === detail?.tracks.length ? new Set() : new Set(detail?.tracks.map((_, i) => i)),
    );
  const allSelected = !!detail && detail.tracks.length > 0 && selected.size === detail.tracks.length;

  const downloadSelected = async () => {
    if (!detail || selected.size === 0) return;
    setBusy(true);
    setBanner(null);
    try {
      const items = Array.from(selected)
        .map((i): DownloadItemInput | null => {
          const t = detail.tracks[i];
          const opts = flattenOptions(t);
          const match =
            opts.find((o) => o.provider === batchProvider && o.tier === batchTier) ||
            opts.find((o) => o.provider === batchProvider) ||
            bestOption(t);
          if (!match) return null;
          return { provider: match.provider, quality: match.tier, track: toTrackPayload(t) };
        })
        .filter((x): x is DownloadItemInput => x !== null);
      if (!items.length) {
        setBanner("Las pistas seleccionadas no tienen fuentes disponibles.");
        return;
      }
      const jobs = await api.enqueue(items);
      setBanner(`${jobs.length} canción(es) añadidas a la cola.`);
      setSelected(new Set());
    } catch (e) {
      setBanner((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="text-slate-400">Cargando álbum…</p>;
  if (error) return <p className="text-red-400">{error}</p>;
  if (!detail) return null;

  return (
    <div>
      <button className="btn-ghost mb-3 px-2 py-1 text-sm" onClick={() => navigate(-1)}>
        ← Volver
      </button>
      <div className="relative overflow-hidden rounded-xl border border-slate-800">
        {detail.album.cover_url && (
          <div
            aria-hidden
            className="absolute inset-0 -z-10 scale-110 bg-cover bg-center opacity-25 blur-2xl"
            style={{ backgroundImage: `url("${detail.album.cover_url}")` }}
          />
        )}
        <div className="absolute inset-0 -z-10 bg-gradient-to-t from-slate-950 via-slate-950/70 to-slate-900/40" />
        <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-end">
          <Artwork
            src={detail.album.cover_url}
            alt={detail.album.title}
            seed={`${detail.album.title} ${detail.album.artist}`}
            rounded="rounded-lg"
            className="h-36 w-36 shadow-2xl ring-1 ring-white/10 sm:h-40 sm:w-40"
          />
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wide text-slate-400">Álbum</p>
            <h1 className="mt-0.5 text-2xl font-bold leading-tight">{detail.album.title}</h1>
            <p className="mt-1 text-slate-300">
              {detail.album.artist}
              {detail.album.year ? ` · ${detail.album.year}` : ""}
            </p>
            <p className="mt-2 text-xs text-slate-400">
              {detail.tracks.length} pistas · no se descargan álbumes enteros: elige pistas.
            </p>
          </div>
        </div>
      </div>

      <div className="card mt-4 flex flex-wrap items-center gap-2">
        <button className="btn-ghost" onClick={toggleAll}>
          {allSelected ? "Quitar selección" : "Seleccionar todo"}
        </button>
        <span className="text-sm text-slate-400">{selected.size} seleccionadas</span>
        <div className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto">
          <select
            className="input min-w-0 flex-1 py-1 sm:flex-none"
            value={batchProvider}
            onChange={(e) => setBatchProvider(e.target.value)}
          >
            {providersAvail.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          <select
            className="input min-w-0 flex-1 py-1 sm:flex-none"
            value={batchTier}
            onChange={(e) => setBatchTier(Number(e.target.value))}
          >
            {tiersAvail.map((t) => (
              <option key={t} value={t}>
                {TIER_LABELS[t]}
              </option>
            ))}
          </select>
          <button
            className="btn-primary"
            disabled={busy || selected.size === 0}
            onClick={downloadSelected}
          >
            Descargar selección
          </button>
        </div>
      </div>

      {banner && (
        <div className="mt-3 rounded-md border border-brand/40 bg-brand/10 px-3 py-2 text-sm text-brand">
          {banner}
        </div>
      )}

      <div className="card mt-4 px-4 py-0">
        {detail.tracks.map((t, i) => (
          <TrackRow
            key={i}
            track={t}
            selectable
            selected={selected.has(i)}
            onToggleSelected={() => toggle(i)}
            onEnqueued={(jobs) => setBanner(`${jobs.length} en la cola`)}
          />
        ))}
      </div>
    </div>
  );
}
