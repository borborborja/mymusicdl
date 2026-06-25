import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

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
  // Search state lives in the URL (?q=…&kind=…) so navigating to an album and pressing back
  // restores the results instead of dropping the user on an empty search box.
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [kind, setKind] = useState<Kind>((searchParams.get("kind") as Kind) ?? "song");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [metadata, setMetadata] = useState<string>("");
  const [selected, setSelected] = useState<string[]>(() => {
    const p = searchParams.get("providers");
    return p ? p.split(",").filter(Boolean) : [];
  });
  const [losslessOnly, setLosslessOnly] = useState(searchParams.get("lossless") === "1");
  const [limit, setLimit] = useState(() => Number(searchParams.get("limit")) || 20);
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

  // Re-run the search captured in the URL when landing here (incl. browser "back" from an album).
  useEffect(() => {
    const urlQ = searchParams.get("q");
    if (urlQ && urlQ.trim() && !data) void runSearch(urlQ, (searchParams.get("kind") as Kind) ?? "song");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runSearch = async (qv = q, kindv = kind) => {
    if (!qv.trim()) return;
    const params: Record<string, string> = { q: qv, kind: kindv };
    if (selected.length) params.providers = selected.join(",");
    if (losslessOnly) params.lossless = "1";
    if (limit !== 20) params.limit = String(limit);
    setSearchParams(params);
    setLoading(true);
    setError(null);
    try {
      const res = await api.search({ q: qv, kind: kindv, providers: selected, losslessOnly, limit });
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
            className="input min-w-0 flex-1"
            placeholder="Artista, álbum o canción…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn-primary shrink-0" disabled={loading}>
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

        <div className="flex flex-wrap items-center gap-3">
          <SourceFilter
            providers={providers}
            selected={selected}
            onSelected={setSelected}
            losslessOnly={losslessOnly}
            onLossless={setLosslessOnly}
          />
          <label className="ml-auto flex items-center gap-1.5 text-sm text-slate-400">
            Resultados
            <select
              className="input py-1"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {[20, 40, 60, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

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
