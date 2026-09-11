import { useRef, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import CatalogNotice from "../components/CatalogNotice";
import CollectionCard from "../components/CollectionCard";
import { useToast } from "../components/Toaster";
import { api } from "../lib/api";
import type { FamilyArtist } from "../lib/types";
import { collectionChanged, useCollection } from "../lib/useCollection";

function ArtistChoices() {
  const {data: artists, error, reload} = useCollection(api.familyArtists);
  const [q, setQ] = useState("");
  const [choices, setChoices] = useState<FamilyArtist[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const toast = useToast();
  const act = (action: () => Promise<unknown>) => {
    setBusy(true);
    void action().then(() => {setChoices([]);collectionChanged();}).catch(e => toast.error(e.message)).finally(() => setBusy(false));
  };
  return <section className="card space-y-3" aria-label="Artistas de la familia">
    <h2 className="font-semibold">¿Qué artistas nos gustan?</h2>
    <p className="text-sm text-slate-400">Elige hasta cinco para descubrir música relacionada. Solo consultamos los artistas elegidos; el historial de escucha no se envía.</p>
    <div className="flex flex-wrap gap-2">{artists?.map(a => <button className="btn-ghost text-sm" key={a.id} disabled={busy} aria-label={`Quitar artista ${a.name}`} onClick={() => act(() => api.removeArtist(a.id))}>{a.name} ×</button>)}</div>
    {error && <p role="alert">{error} <button className="underline" onClick={reload}>Reintentar</button></p>}
    <form className="flex gap-2" onSubmit={e => {
      e.preventDefault(); if (!q.trim()) return;
      const current = ++sequence.current;
      setBusy(true);setSearchError(null);
      void api.artistChoices(q).then(rows => {if (current === sequence.current) setChoices(rows);}).catch(e => {if (current === sequence.current) setSearchError(e.message);}).finally(() => {if (current === sequence.current) setBusy(false);});
    }}>
      <input className="input min-w-0 flex-1" aria-label="Buscar artista para descubrir" placeholder="Nombre del artista…" value={q} onChange={e => {++sequence.current;setQ(e.target.value);setChoices([]);setBusy(false);}} />
      <button className="btn-primary" disabled={busy || !q.trim() || (artists?.length ?? 0) >= 5}>Buscar artista</button>
    </form>
    {searchError && <p className="text-amber-300" role="alert">{searchError}</p>}
    {busy && <p role="status" className="text-sm">Consultando…</p>}
    <div className="space-y-1">{choices.map(a => <button key={a.id} className="block w-full rounded border border-slate-700 px-3 py-2 text-left hover:bg-slate-800" disabled={busy || artists?.some(x => x.id === a.id) || (artists?.length ?? 0) >= 5} onClick={() => act(() => api.chooseArtist(a))}>{a.name}<span className="block text-xs text-slate-400">{a.disambiguation || "MusicBrainz"} · {a.id.slice(0, 8)}</span></button>)}</div>
  </section>;
}

export default function DiscoverPage() {
  const location = useLocation();
  const local = useCollection(() => api.discovery("local"));
  const external = useCollection(() => api.discovery("external"));
  const saved = useCollection(() => api.familyTracks());
  const [showAll, setShowAll] = useState(false);
  if (location.search && new URLSearchParams(location.search).has("kind")) return <Navigate replace to={`/search${location.search}`} />;
  if (local.data?.enabled === false) return <Navigate replace to="/search" />;
  return <div className="space-y-6">
    <div><h1 className="text-2xl font-semibold">Descubrir en familia</h1><p className="mt-1 text-slate-400">Encuentra algo que apetezca escuchar y guarda lo que quieras añadir.</p></div>
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">De nuestra biblioteca</h2><Link className="text-sm text-brand underline" to="/library">Ver toda la biblioteca</Link></div>
      <CatalogNotice status={local.data?.status} />
      {local.error && <p role="alert" className="text-amber-300">{local.error} <button className="underline" onClick={local.reload}>Reintentar</button></p>}
      {local.loading && !local.data && <p role="status">Cargando biblioteca…</p>}
      {local.data && !local.data.items.length && <p className="text-slate-400">La selección aparecerá cuando se actualice el catálogo de Navidrome.</p>}
      <div className="grid gap-3 md:grid-cols-2">{local.data?.items.slice(0, 6).map(card => <CollectionCard key={card.track.catalog_id ?? card.id} card={card} />)}</div>
    </section>
    <ArtistChoices />
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">A partir de los artistas que nos gustan</h2>
      <p className="text-sm text-slate-400">Sugerencias de ListenBrainz. Guardarlas no inicia ninguna descarga.</p>
      {external.data?.enabled === false && <p>Las sugerencias externas están desactivadas.</p>}
      {external.error && <p role="alert" className="text-amber-300">{external.error} <button className="underline" onClick={external.reload}>Reintentar</button></p>}
      {external.data?.error && <p role="status" className="text-amber-300">{external.data.error}</p>}
      {external.data?.refreshing && <p role="status">Preparando sugerencias en segundo plano… Puedes seguir explorando la biblioteca.</p>}
      {external.data?.updated_at && <p className="text-xs text-slate-400">{external.data.stale ? "Últimas sugerencias disponibles" : "Actualizadas"}: {new Date(external.data.updated_at).toLocaleString()}</p>}
      {external.data?.enabled && !external.data.items.length && !external.data.refreshing && <p className="text-slate-400">{external.data.artists?.length ? "No hay sugerencias nuevas. Puedes cambiar los artistas o recuperar pistas descartadas." : "Elige un artista para empezar."}</p>}
      <div className="grid gap-3 md:grid-cols-2">{external.data?.items.slice(0, showAll ? 20 : 6).map(card => <CollectionCard key={card.id} card={card} />)}</div>
      {(external.data?.items.length ?? 0) > 6 && <button className="btn-ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Ver menos" : `Ver las ${external.data!.items.length} sugerencias`}</button>}
    </section>
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2"><h2 className="text-lg font-semibold">Lo tenemos pendiente</h2><Link className="text-sm text-brand underline" to="/saved">Ver nuestra selección</Link></div>
      {saved.error && <p role="alert">{saved.error}</p>}
      {saved.data && !saved.data.items.length && <p className="text-slate-400">Guarda una canción desde la búsqueda, la biblioteca o las sugerencias.</p>}
      <div className="grid gap-3 md:grid-cols-2">{saved.data?.items.slice(0, 4).map(card => <CollectionCard key={card.id} card={card} />)}</div>
    </section>
  </div>;
}
