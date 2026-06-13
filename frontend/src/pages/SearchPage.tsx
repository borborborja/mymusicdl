import { useEffect, useState } from "react";

import SourceFilter from "../components/SourceFilter";
import { api } from "../lib/api";
import type { ProviderInfo, SearchResponse } from "../lib/types";
import ResultsPage from "./ResultsPage";

type Kind = "song" | "album" | "artist";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<Kind>("song");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [losslessOnly, setLosslessOnly] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settings().then((s) => setProviders(s.providers)).catch(() => undefined);
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
          <select
            className="input"
            value={kind}
            onChange={(e) => setKind(e.target.value as Kind)}
          >
            <option value="song">Canción</option>
            <option value="album">Álbum</option>
            <option value="artist">Artista</option>
          </select>
          <button type="submit" className="btn-primary" disabled={loading}>
            Buscar
          </button>
        </div>
        <SourceFilter
          providers={providers}
          selected={selected}
          onSelected={setSelected}
          losslessOnly={losslessOnly}
          onLossless={setLosslessOnly}
        />
      </form>

      <ResultsPage data={data} loading={loading} error={error} onArtistPick={onArtistPick} />
    </div>
  );
}
