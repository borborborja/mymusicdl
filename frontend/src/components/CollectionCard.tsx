import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { togglePreview } from "../lib/preview";
import type { CollectionCard as Card } from "../lib/types";
import { collectionChanged } from "../lib/useCollection";
import Artwork from "./Artwork";
import DownloadedAudio from "./DownloadedAudio";
import { useToast } from "./Toaster";

const labels = {available: "Ya disponible", unknown: "Disponibilidad desconocida", missing: "Por añadir", downloading: "Descargando", pending: "Pendiente de Navidrome", failed: "Descarga interrumpida"};

export default function CollectionCard({card}: {card: Card}) {
  const [busy, setBusy] = useState(false);
  const [provider, setProvider] = useState("ytdlp");
  const toast = useToast();
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try { await action(); collectionChanged(); }
    catch (e) { toast.error((e as Error).message); }
    finally { setBusy(false); }
  };
  const canDownload = !card.catalog_id && !card.local_item_id && !card.job_done && !["available", "downloading", "pending"].includes(card.availability);
  const t = card.track;
  return <article className="card min-w-0 space-y-3" aria-label={`${t.artist} — ${t.title}`}>
    <div className="flex items-start gap-3">
      <Artwork src={t.cover_url} alt="" seed={`${t.artist} ${t.album ?? t.title}`} rounded="rounded" className="h-14 w-14 shrink-0" />
      <div className="min-w-0 flex-1">
        <h3 className="break-words font-medium">{t.title}</h3>
        <p className="break-words text-sm text-slate-400">{t.artist}{t.album ? ` · ${t.album}` : ""}</p>
      </div>
    </div>
    <div className="flex flex-wrap gap-2 text-xs">
      <span className={card.availability === "available" ? "text-emerald-400" : "text-slate-400"}>{labels[card.availability]}</span>
      {card.saved && <span className="text-brand">Guardada en pendientes</span>}
      {card.format && <span className="text-slate-400">{card.format.toUpperCase()}{card.bitrate_kbps ? ` · ${card.bitrate_kbps} kbps` : ""}</span>}
    </div>
    {card.reason && <p className="text-xs text-slate-400">{card.reason}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="btn-ghost text-xs" disabled={busy} aria-pressed={card.saved} onClick={() => void act(() => api.preference(t, {saved: !card.saved}))}>{card.saved ? "Quitar de pendientes" : "Guardar para después"}</button>
      <button className="btn-ghost text-xs" disabled={busy} aria-pressed={card.favorite} onClick={() => void act(() => api.preference(t, {favorite: !card.favorite}))}>{card.favorite ? "♥ Favorita" : "♡ Favorita"}</button>
      <button className="btn-ghost text-xs" disabled={busy} onClick={() => void act(() => api.preference(t, {dismissed: !card.dismissed}))}>{card.dismissed ? "Volver a sugerir" : "No sugerir"}</button>
    </div>
    {card.local_item_id ? <DownloadedAudio itemId={card.local_item_id} title={t.title} /> : card.job_done && card.job_id ? <DownloadedAudio jobId={card.job_id} title={t.title} /> : card.catalog_id ? <DownloadedAudio catalogId={card.catalog_id} title={t.title} /> : <button className="btn-ghost text-xs" onClick={() => void togglePreview(card.id, async () => (await api.preview(t)).url).catch(() => toast.error("La previsualización externa no está disponible."))}>▶ Vista previa externa · orientativa</button>}
    {canDownload && <div className="flex flex-wrap items-center gap-2">
      <select aria-label={`Fuente para ${t.title}`} className="input min-w-0 py-1 text-sm" value={provider} onChange={e => setProvider(e.target.value)}>
        <option value="ytdlp">YouTube · MP3</option><option value="spotdl">spotDL · MP3</option>
      </select>
      <button className="btn-primary text-sm" disabled={busy} onClick={() => void act(async () => {
        const saved = await api.preference(t, {saved: true});
        await api.familyDownload(saved.id, provider);
        toast.success("Añadida a la cola. Puedes seguir su llegada a Navidrome.");
      })}>{busy ? "Añadiendo…" : "Añadir a la biblioteca"}</button>
    </div>}
    {card.job_id && <Link className="text-xs text-brand underline" to="/queue">Ver descarga y sincronización</Link>}
    {card.error && <p className="text-xs text-amber-300">{card.error}</p>}
  </article>;
}
