import { useEffect, useState } from "react";

import SourceFilter from "../components/SourceFilter";
import { api } from "../lib/api";
import type { ProviderInfo, SearchResponse } from "../lib/types";
import ResultsPage from "./ResultsPage";

type Kind = "song" | "album" | "artist";

const KINDS: { value: Kind; label: string }[] = [
  { value: "song", label: "Canciones" },
  { value: "album", label: "Álbumes" },
  { value: "artist", label: "Artistas" },
];

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<Kind>("song");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [metadata, setMetadata] = useState<string>("");
  const [selected, setSelected] = useState<string[]>([]);
  const [losslessOnly, setLosslessOnly] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setProviders(s.providers);
        setMetadata(s.metadata);
      })
      .catch(() => undefined);
  }, []);

  const runSearch = async (qv = q, kindv = kind) => {
    if (!qv.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.search({ q: qv, kind: kindv, providers: selected, losslessOnly });
      setData(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const onArtistPick = (name: string) => {
    setQ(name);
    setKind("album");
    void runSearch(name, "album");
  };

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch();
        }}
        className="card space-y-3"
      >
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Artista, álbum o canción…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn-primary" disabled={loading}>
            Buscar
          </button>
        </div>

        <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
          {KINDS.map((k) => (
            <button
              key={k.value}
              type="button"
              onClick={() => setKind(k.value)}
              className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${
                kind === k.value
                  ? "bg-brand text-slate-950"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              {k.label}
            </button>
          ))}
        </div>

        <SourceFilter
          providers={providers}
          selected={selected}
          onSelected={setSelected}
          losslessOnly={losslessOnly}
          onLossless={setLosslessOnly}
        />

        {metadata === "musicbrainz" && (
          <p className="text-xs text-slate-500">
            Catálogo vía <span className="text-slate-300">MusicBrainz</span> · carátulas de{" "}
            <span className="text-slate-300">Cover Art Archive</span>. Añade credenciales de
            Spotify en Ajustes para fotos de artista y mejores coincidencias.
          </p>
        )}
      </form>

      <ResultsPage data={data} loading={loading} error={error} onArtistPick={onArtistPick} />
    </div>
  );
}
