import { useEffect, useMemo, useState } from "react";
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

const PLACEHOLDERS: Record<Kind, string> = {
  song: "Canción o texto libre…",
  album: "Álbum…",
  artist: "Artista…",
};

interface Fields {
  q: string;
  kind: Kind;
  artist: string;
  album: string;
  year: string;
}

export default function SearchPage() {
  // Search state lives in the URL (?q=…&kind=…) so navigating to an album and pressing back
  // restores the results instead of dropping the user on an empty search box.
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [kind, setKind] = useState<Kind>((searchParams.get("kind") as Kind) ?? "song");
  const [artist, setArtist] = useState(searchParams.get("artist") ?? "");
  const [album, setAlbum] = useState(searchParams.get("album") ?? "");
  const [year, setYear] = useState(searchParams.get("year") ?? "");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [metadata, setMetadata] = useState<string>("");
  const [selected, setSelected] = useState<string[]>(() => {
    const p = searchParams.get("providers");
    return p ? p.split(",").filter(Boolean) : [];
  });
  const [losslessOnly, setLosslessOnly] = useState(searchParams.get("lossless") === "1");
  const [limit, setLimit] = useState(() => Number(searchParams.get("limit")) || 20);
  const [sort, setSort] = useState(searchParams.get("sort") ?? "relevance");
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
    const urlQ = searchParams.get("q") ?? "";
    const urlArtist = searchParams.get("artist") ?? "";
    const urlAlbum = searchParams.get("album") ?? "";
    if ((urlQ.trim() || urlArtist.trim() || urlAlbum.trim()) && !data)
      void runSearch({
        q: urlQ,
        kind: (searchParams.get("kind") as Kind) ?? "song",
        artist: urlArtist,
        album: urlAlbum,
        year: searchParams.get("year") ?? "",
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runSearch = async (overrides: Partial<Fields> = {}) => {
    const f: Fields = { q, kind, artist, album, year, ...overrides };
    // "artist" searches only take the main box; the fielded filters apply to songs/albums.
    if (f.kind === "artist" && !f.q.trim()) return;
    if (!f.q.trim() && !f.artist.trim() && !f.album.trim()) return;
    const params: Record<string, string> = { kind: f.kind };
    if (f.q.trim()) params.q = f.q;
    if (f.kind !== "artist") {
      if (f.artist.trim()) params.artist = f.artist;
      if (f.kind === "song" && f.album.trim()) params.album = f.album;
      if (f.year.trim()) params.year = f.year;
    }
    if (selected.length) params.providers = selected.join(",");
    if (losslessOnly) params.lossless = "1";
    if (limit !== 20) params.limit = String(limit);
    if (sort !== "relevance") params.sort = sort;
    setSearchParams(params);
    setLoading(true);
    setError(null);
    try {
      const res = await api.search({
        q: params.q ?? "",
        kind: f.kind,
        artist: params.artist,
        album: params.album,
        year: params.year,
        providers: selected,
        losslessOnly,
        limit,
      });
      setData(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Year sorting is client-side over the fetched page, so flipping it doesn't re-query.
  const sortedData = useMemo(() => {
    if (!data || data.kind !== "album" || sort === "relevance") return data;
    const albums = [...data.albums].sort((a, b) => {
      if (a.year == null) return 1;
      if (b.year == null) return -1;
      return sort === "year_asc" ? a.year - b.year : b.year - a.year;
    });
    return { ...data, albums };
  }, [data, sort]);

  const onArtistPick = (name: string) => {
    setQ("");
    setArtist(name);
    setKind("album");
    void runSearch({ q: "", artist: name, kind: "album" });
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
            placeholder={PLACEHOLDERS[kind]}
            aria-label="Búsqueda principal"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn-primary shrink-0" disabled={loading}>
            Buscar
          </button>
        </div>

        {kind !== "artist" && (
          <div className="flex flex-wrap gap-2">
            <input
              className="input min-w-0 flex-1 basis-40"
              placeholder="Artista (opcional)"
              aria-label="Artista (opcional)"
              value={artist}
              onChange={(e) => setArtist(e.target.value)}
            />
            {kind === "song" && (
              <input
                className="input min-w-0 flex-1 basis-40"
                placeholder="Álbum (opcional)"
                aria-label="Álbum (opcional)"
                value={album}
                onChange={(e) => setAlbum(e.target.value)}
              />
            )}
            <input
              className="input w-24 shrink-0"
              placeholder="Año"
              aria-label="Año"
              inputMode="numeric"
              value={year}
              onChange={(e) => setYear(e.target.value)}
            />
          </div>
        )}

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
          {kind === "album" && (
            <label className="ml-auto flex items-center gap-1.5 text-sm text-slate-400">
              Ordenar
              <select className="input py-1" value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="relevance">Relevancia</option>
                <option value="year_desc">Año ↓ (recientes)</option>
                <option value="year_asc">Año ↑ (antiguos)</option>
              </select>
            </label>
          )}
          <label
            className={`flex items-center gap-1.5 text-sm text-slate-400 ${
              kind === "album" ? "" : "ml-auto"
            }`}
          >
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

      <ResultsPage
        data={sortedData}
        loading={loading}
        error={error}
        emptyHint={
          searchParams.get("artist")
            ? searchParams.get("kind") === "album"
              ? "Los discos de un artista pueden estar a nombre de su grupo (p. ej. Pau Donés → Jarabe de Palo). Prueba con el nombre del grupo, o busca sus canciones en Canciones."
              : "Prueba con menos filtros o revisa la ortografía."
            : undefined
        }
        onArtistPick={onArtistPick}
      />
    </div>
  );
}
