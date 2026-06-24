import { useEffect } from "react";

import ProgressBar from "../components/ProgressBar";
import { api } from "../lib/api";
import { setJobs, useJobs } from "../store/jobs";

const STATUS_STYLE: Record<string, string> = {
  queued: "text-slate-400",
  running: "text-brand",
  done: "text-emerald-400",
  error: "text-red-400",
  canceled: "text-amber-400",
};

export default function QueuePage() {
  const jobs = useJobs();

  useEffect(() => {
    api.listJobs().then(setJobs).catch(() => undefined);
  }, []);

  const cancel = (id: string) => void api.cancelJob(id).catch(() => undefined);
  const retry = (id: string) => void api.retryJob(id).catch(() => undefined);

  if (!jobs.length) return <p className="text-slate-500">No hay descargas todavía.</p>;

  return (
    <div className="space-y-2">
      {jobs.map((j) => {
        const indeterminate = j.status === "running" && !j.progress_pct;
        return (
          <div key={j.id} className="card">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  {j.origin && j.origin !== "web" && (
                    <span
                      title={`Añadida desde ${j.origin}`}
                      className="shrink-0 text-brand"
                      aria-label={`Añadida vía ${j.origin}`}
                    >
                      📱
                    </span>
                  )}
                  <span className="truncate font-medium">{j.title ?? j.id}</span>
                </div>
                <div className="text-xs text-slate-500">
                  {j.provider ?? j.kind}
                  {j.stage ? ` · ${j.stage}` : ""}
                  {j.origin && j.origin !== "web" ? ` · vía ${j.origin}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs font-medium ${STATUS_STYLE[j.status] ?? "text-slate-400"}`}>
                  {j.status}
                </span>
                {(j.status === "queued" || j.status === "running") && (
                  <button className="btn-ghost px-2 py-1 text-xs" onClick={() => cancel(j.id)}>
                    Cancelar
                  </button>
                )}
                {(j.status === "error" || j.status === "canceled") && (
                  <button className="btn-ghost px-2 py-1 text-xs" onClick={() => retry(j.id)}>
                    Reintentar
                  </button>
                )}
              </div>
            </div>
            {(j.status === "running" || j.status === "queued") && (
              <div className="mt-2">
                <ProgressBar pct={j.progress_pct} indeterminate={indeterminate} />
              </div>
            )}
            {j.error && <p className="mt-2 whitespace-pre-wrap text-xs text-red-400">{j.error}</p>}
            {j.status === "done" && (
              <p
                className={`mt-1 text-xs ${
                  j.library_confirmed === true
                    ? "text-emerald-400"
                    : j.library_confirmed === false
                      ? "text-amber-400"
                      : "text-slate-400"
                }`}
              >
                {j.library_confirmed === true
                  ? "✓ en Navidrome"
                  : j.library_confirmed === false
                    ? "⚠ aún no aparece en Navidrome"
                    : "⏳ comprobando en Navidrome…"}
              </p>
            )}
            {j.status === "done" && j.result_path && (
              <p className="mt-1 truncate text-xs text-slate-500">{j.result_path}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
