import { useState } from "react";
import CollectionCard from "../components/CollectionCard";
import { api } from "../lib/api";
import { useCollection } from "../lib/useCollection";

export default function SavedPage() {
  const [mode, setMode] = useState("saved");
  const [offset, setOffset] = useState(0);
  const {data, loading, error, reload} = useCollection(() => api.familyTracks(mode, offset), [mode, offset]);
  return <div className="space-y-4">
    <h1 className="text-xl font-semibold">Nuestra selección</h1>
    <p className="text-sm text-slate-400">Guardar no descarga nada. Decide qué escuchar o añadir cuando te apetezca.</p>
    <div className="flex flex-wrap gap-2">{[["saved", "Pendientes"], ["favorite", "Favoritas"], ["dismissed", "Descartadas"]].map(([key, label]) => <button key={key} className={mode === key ? "btn-primary" : "btn-ghost"} aria-pressed={mode === key} onClick={() => {setMode(key);setOffset(0);}}>{label}</button>)}</div>
    {error && <p role="alert" className="text-red-400">{error} <button onClick={reload} className="underline">Reintentar</button></p>}
    {loading && !data && <p role="status">Cargando selección…</p>}
    {data && !data.items.length && <p className="text-slate-400">Todavía no hay pistas en esta selección. Puedes guardarlas desde Descubrir, Buscar o Biblioteca.</p>}
    <div className="grid gap-3 md:grid-cols-2">{data?.items.map(card => <CollectionCard key={card.id} card={card} />)}</div>
    <div className="flex justify-between"><button className="btn-ghost" disabled={!offset || loading} onClick={() => setOffset(Math.max(0, offset - 40))}>Anterior</button><button className="btn-ghost" disabled={!data?.has_more || loading} onClick={() => setOffset(offset + 40)}>Siguiente</button></div>
  </div>;
}
