import type { CatalogStatus } from "../lib/types";
export default function CatalogNotice({status}: {status?: CatalogStatus}) {
  if (!status) return null;
  return <div className="space-y-1 text-sm text-slate-400" role="status">
    {!status.configured && <p>Configura Navidrome para explorar toda la biblioteca. Tus descargas locales y pendientes siguen disponibles.</p>}
    {status.refreshing && <p>Actualizando la biblioteca en segundo plano…</p>}
    {status.error && <p className="text-amber-300">{status.error}</p>}
    {status.updated_at && <p>{status.stale ? "Última biblioteca disponible" : "Biblioteca actualizada"}: {new Date(status.updated_at).toLocaleString()}</p>}
  </div>;
}
