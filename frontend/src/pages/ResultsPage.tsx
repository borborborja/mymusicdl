import { useState } from "react";

import { AlbumCard, ArtistCard } from "../components/ResultCard";
import TrackRow from "../components/TrackRow";
import type { SearchResponse } from "../lib/types";

export default function ResultsPage({
  data,
  loading,
  error,
  onArtistPick,
}: {
  data: SearchResponse | null;
  loading: boolean;
  error: string | null;
  onArtistPick: (name: string) => void;
}) {
  const [banner, setBanner] = useState<string | null>(null);

  if (loading) return <p className="mt-8 text-center text-slate-400">Buscando…</p>;
  if (error) return <p className="mt-8 text-center text-red-400">{error}</p>;
  if (!data) return <p className="mt-8 text-center text-slate-500">Busca por artista, álbum o canción.</p>;

  return (
    <div className="mt-4">
      {banner && (
        <div className="mb-3 rounded-md border border-brand/40 bg-brand/10 px-3 py-2 text-sm text-brand">
          {banner}
        </div>
      )}

      {data.kind === "song" && (
        <div className="card divide-y divide-slate-800 p-0">
          {data.tracks.length === 0 && <p className="p-4 text-slate-500">Sin resultados.</p>}
          {data.tracks.map((t, i) => (
            <div key={`${t.title}-${i}`} className="px-4">
              <TrackRow track={t} onEnqueued={(jobs) => setBanner(`${jobs.length} canción(es) en la cola`)} />
            </div>
          ))}
        </div>
      )}

      {data.kind === "album" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.albums.length === 0 && <p className="text-slate-500">Sin resultados.</p>}
          {data.albums.map((a) => (
            <AlbumCard key={`${a.provider}-${a.id}`} album={a} />
          ))}
        </div>
      )}

      {data.kind === "artist" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.artists.length === 0 && <p className="text-slate-500">Sin resultados.</p>}
          {data.artists.map((a) => (
            <ArtistCard key={`${a.provider}-${a.id}`} artist={a} onPick={onArtistPick} />
          ))}
        </div>
      )}
    </div>
  );
}
