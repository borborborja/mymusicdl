import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import CatalogNotice from "../components/CatalogNotice";
import CollectionCard from "../components/CollectionCard";
import { useToast } from "../components/Toaster";
import { api } from "../lib/api";
import { useCollection } from "../lib/useCollection";

export default function CatalogPage() {
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState("artist");
  const [refreshing, setRefreshing] = useState(false);
  const toast = useToast();
  const snapshot = useRef<string | null>(null);
  const {data, error, loading, reload} = useCollection(async () => {
    const page = await api.catalog(q, offset, sort, 40, offset ? snapshot.current : null);
    snapshot.current = page.status.generation ?? null;
    return page;
  }, [q, offset, sort]);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h1 className="text-xl font-semibold">Biblioteca familiar</h1><Link className="text-sm text-brand underline" to="/library/downloads">Archivos descargados por mymusicdl</Link></div>
    <p className="text-sm text-slate-400">Toda la música accesible en Navidrome. Los gustos y pendientes se comparten en familia.</p>
    <CatalogNotice status={data?.status} />
    <form className="flex flex-wrap gap-2" onSubmit={e => {e.preventDefault(); setOffset(0); setQ(query); reload();}}>
      <input aria-label="Buscar en la biblioteca" className="input min-w-0 flex-1 basis-48" placeholder="Canción, artista o álbum…" value={query} onChange={e => setQuery(e.target.value)} />
      <button className="btn-primary">Buscar</button>
      <select className="input" aria-label="Ordenar biblioteca" value={sort} onChange={e => {setOffset(0);setSort(e.target.value);}}><option value="artist">Artista</option><option value="title">Título</option><option value="recent">Actualizadas</option></select>
      <button type="button" className="btn-ghost" disabled={refreshing || data?.status.refreshing || !data?.status.configured} onClick={() => {
        setRefreshing(true);
        void api.refreshCatalog().then(() => {toast.success("Actualización solicitada.");reload();}).catch(e => toast.error(e.message)).finally(() => setRefreshing(false));
      }}>Actualizar catálogo</button>
    </form>
    {error && <p role="alert" className="text-red-400">{error} <button className="underline" onClick={() => {setOffset(0); reload();}}>Reintentar desde el inicio</button></p>}
    {loading && !data && <p role="status">Cargando biblioteca…</p>}
    {data && <>
      <p className="text-sm text-slate-400">{data.total} pistas{data.total > 0 ? ` · ${offset + 1}–${Math.min(offset + 40, data.total)}` : ""}</p>
      {!data.items.length && <p>No hay pistas que mostrar. Puedes actualizar el catálogo o cambiar la búsqueda.</p>}
      <div className="grid gap-3 md:grid-cols-2">{data.items.map(card => <CollectionCard key={card.track.catalog_id ?? card.id} card={card} />)}</div>
      <div className="flex justify-between"><button className="btn-ghost" disabled={!offset || loading} onClick={() => setOffset(Math.max(0, offset - 40))}>Anterior</button><button className="btn-ghost" disabled={offset + 40 >= data.total || loading} onClick={() => setOffset(offset + 40)}>Siguiente</button></div>
    </>}
  </div>;
}
