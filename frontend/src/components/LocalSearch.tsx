import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useCollection } from "../lib/useCollection";
import CatalogNotice from "./CatalogNotice";
import CollectionCard from "./CollectionCard";
export default function LocalSearch({query}: {query: string}) {
  const {data, loading, error} = useCollection(() => api.catalog(query, 0, "artist", 4), [query]);
  return <section className="my-4 space-y-3" aria-label="Resultados locales">
    <div className="flex justify-between gap-2"><h2 className="font-semibold">En nuestra biblioteca</h2><Link className="text-sm text-brand underline" to="/library">Explorar biblioteca</Link></div>
    <CatalogNotice status={data?.status} />
    {loading && !data && <p>Cargando resultados locales…</p>}
    {error && <p role="alert">{error}</p>}
    {data && !data.items.length && <p className="text-sm text-slate-400">No hay coincidencias en el último catálogo disponible.</p>}
    <div className="grid gap-3 md:grid-cols-2">{data?.items.map(card => <CollectionCard key={card.track.catalog_id ?? card.id} card={card} />)}</div>
  </section>;
}
