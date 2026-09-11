import { useState } from "react";

import { api } from "../lib/api";
import { stopPreview } from "../lib/preview";

/** Plays the saved file itself; independent of YouTube and Navidrome availability. */
export default function DownloadedAudio({ jobId, itemId, catalogId, title }: {
  jobId?: string;
  itemId?: number;
  catalogId?: string;
  title: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = catalogId ? await api.catalogPlayback(catalogId) : jobId ? await api.jobPlayback(jobId) : await api.libraryPlayback(itemId!);
      setUrl(result.url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 min-w-0 space-y-1">
      {!url ? (
        <button className="btn-ghost px-2 py-1 text-xs" disabled={busy} onClick={() => void open()}>
          {busy ? "Abriendo archivo…" : catalogId ? "▶ Escuchar en Navidrome" : "▶ Escuchar archivo descargado"}
        </button>
      ) : (
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-2 text-xs text-slate-400">
            <span>{catalogId ? "Archivo de Navidrome" : "Archivo descargado"} · {title}</span>
            <button className="btn-ghost px-2 py-1" onClick={() => { setUrl(null); setError(null); }}>
              Cerrar reproductor
            </button>
          </div>
          <audio
            aria-label={`Escuchar ${title}`}
            className="h-10 w-full max-w-lg"
            controls autoPlay preload="metadata" src={url}
            onPlay={(event) => {
              stopPreview();
              document.querySelectorAll("audio").forEach((audio) => {
                if (audio !== event.currentTarget) audio.pause();
              });
            }}
            onError={() => setError("No se pudo reproducir el archivo. Puedes abrirlo directamente o cerrar y reabrir el reproductor.")}
          />
          <a className="text-xs text-brand underline" href={url} target="_blank" rel="noreferrer">
            Abrir archivo original
          </a>
        </div>
      )}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
