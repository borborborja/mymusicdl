import { useEffect, useMemo, useState } from "react";

import { useConfirm } from "../components/ConfirmDialog";
import ProgressBar from "../components/ProgressBar";
import { useToast } from "../components/Toaster";
import { api } from "../lib/api";
import { formatDuration } from "../lib/util";
import { removeFinished, removeJob, setJobs, useJobs } from "../store/jobs";

const TERMINAL = ["done", "error", "canceled"];

const STATUS_STYLE: Record<string, string> = {
  queued: "text-slate-400",
  running: "text-brand",
  done: "text-emerald-400",
  error: "text-red-400",
  canceled: "text-amber-400",
};

type Filter = "all" | "active" | "done" | "error";
const FILTERS: { value: Filter; label: string; match: (s: string) => boolean }[] = [
  { value: "all", label: "Todas", match: () => true },
  { value: "active", label: "En curso", match: (s) => s === "running" || s === "queued" },
  { value: "done", label: "Terminadas", match: (s) => s === "done" },
  { value: "error", label: "Errores", match: (s) => s === "error" || s === "canceled" },
];

export default function QueuePage() {
  const jobs = useJobs();
  const toast = useToast();
  const confirm = useConfirm();
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.listJobs().then(setJobs).catch(() => undefined);
  }, []);

  const shown = useMemo(() => {
    const m = FILTERS.find((f) => f.value === filter)!.match;
    return jobs.filter((j) => m(j.status));
  }, [jobs, filter]);

  // Drop selections that scrolled out of the current filter.
  useEffect(() => {
    setSelected((prev) => {
      const visible = new Set(shown.map((j) => j.id));
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [shown]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const allShownSelected = shown.length > 0 && shown.every((j) => selected.has(j.id));
  const toggleAll = () =>
    setSelected(allShownSelected ? new Set() : new Set(shown.map((j) => j.id)));

  const cancel = (id: string) => void api.cancelJob(id).catch(() => undefined);
  const retry = (id: string) => void api.retryJob(id).catch(() => undefined);
  const recheck = (id: string) => void api.recheckJob(id).catch(() => undefined);
  const remove = async (id: string) => {
    if (!(await confirm({ title: "¿Quitar esta descarga de la lista?", danger: true, confirmLabel: "Quitar" })))
      return;
    removeJob(id);
    void api.deleteJob(id).catch(() => undefined);
  };
  const clearFinished = async () => {
    if (
      !(await confirm({
        title: "¿Limpiar las descargas terminadas?",
        body: "Se quitan de la lista las completadas, con error y canceladas.",
        confirmLabel: "Limpiar",
        danger: true,
      }))
    )
      return;
    removeFinished();
    void api.clearJobs().catch(() => undefined);
  };
  const recheckAll = () => {
    jobs
      .filter((j) => j.status === "done" && j.library_confirmed === false)
      .forEach((j) => void api.recheckJob(j.id).catch(() => undefined));
  };
  const reindex = () => {
    toast.show("Reindexando Navidrome…");
    api
      .rescan()
      .then(() => toast.success("Reindexado de Navidrome solicitado."))
      .catch((e) => toast.error((e as Error).message));
  };

  // ── batch actions over the current selection ──
  const selectedJobs = () => jobs.filter((j) => selected.has(j.id));
  const batchCancel = () => {
    selectedJobs()
      .filter((j) => j.status === "queued" || j.status === "running")
      .forEach((j) => void api.cancelJob(j.id).catch(() => undefined));
  };
  const batchRetry = () => {
    selectedJobs()
      .filter((j) => j.status === "error" || j.status === "canceled")
      .forEach((j) => void api.retryJob(j.id).catch(() => undefined));
  };
  const batchRemove = async () => {
    const ids = selectedJobs()
      .filter((j) => TERMINAL.includes(j.status))
      .map((j) => j.id);
    if (!ids.length) return;
    if (
      !(await confirm({
        title: `¿Quitar ${ids.length} descarga(s) de la lista?`,
        danger: true,
        confirmLabel: "Quitar",
      }))
    )
      return;
    ids.forEach((id) => {
      removeJob(id);
      void api.deleteJob(id).catch(() => undefined);
    });
    setSelected(new Set());
  };

  const hasFinished = jobs.some((j) => TERMINAL.includes(j.status));
  const hasUnconfirmed = jobs.some((j) => j.status === "done" && j.library_confirmed === false);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    jobs.forEach((j) => (c[j.status] = (c[j.status] ?? 0) + 1));
    return c;
  }, [jobs]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setFilter(f.value)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                filter === f.value ? "bg-brand text-slate-950" : "text-slate-300 hover:text-white"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {hasUnconfirmed && (
            <button className="btn-ghost px-2 py-1 text-xs" onClick={recheckAll}>
              ↻ Comprobar todas en Navidrome
            </button>
          )}
          <button className="btn-ghost px-2 py-1 text-xs" onClick={reindex}>
            🔄 Reindexar Navidrome
          </button>
          {hasFinished && (
            <button className="btn-ghost px-2 py-1 text-xs" onClick={clearFinished}>
              Limpiar terminadas
            </button>
          )}
        </div>
      </div>

      {shown.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-1 text-xs text-slate-400">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={allShownSelected} onChange={toggleAll} />
            {selected.size ? `${selected.size} seleccionada(s)` : "Seleccionar"}
          </label>
          {selected.size > 0 && (
            <>
              <button className="btn-ghost px-2 py-0.5 text-xs" onClick={batchCancel}>
                Cancelar
              </button>
              <button className="btn-ghost px-2 py-0.5 text-xs" onClick={batchRetry}>
                Reintentar
              </button>
              <button className="btn-ghost px-2 py-0.5 text-xs" onClick={batchRemove}>
                Quitar
              </button>
            </>
          )}
        </div>
      )}

      {!jobs.length && <p className="text-slate-500">No hay descargas todavía.</p>}
      {jobs.length > 0 && !shown.length && (
        <p className="text-slate-500">
          Sin descargas {FILTERS.find((f) => f.value === filter)!.label.toLowerCase()}.
          {counts.error ? ` (${counts.error} con error en otros filtros)` : ""}
        </p>
      )}
      {shown.map((j) => {
        const indeterminate = j.status === "running" && !j.progress_pct;
        return (
          <div key={j.id} className="card">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <input
                  type="checkbox"
                  className="shrink-0"
                  aria-label={`Seleccionar ${j.title ?? j.id}`}
                  checked={selected.has(j.id)}
                  onChange={() => toggle(j.id)}
                />
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
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
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
                {TERMINAL.includes(j.status) && (
                  <button
                    className="btn-ghost px-2 py-1 text-xs"
                    aria-label="Quitar"
                    title="Quitar de la lista"
                    onClick={() => remove(j.id)}
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
            {(j.status === "running" || j.status === "queued") && (
              <div className="mt-2">
                <ProgressBar pct={j.progress_pct} indeterminate={indeterminate} />
                {j.status === "running" && (j.speed || j.eta_s != null) && (
                  <div className="mt-1 text-xs text-slate-500">
                    {j.speed ? <span>{j.speed}</span> : null}
                    {j.speed && j.eta_s != null ? " · " : ""}
                    {j.eta_s != null ? <span>ETA {formatDuration(j.eta_s)}</span> : null}
                  </div>
                )}
              </div>
            )}
            {j.error && <p className="mt-2 whitespace-pre-wrap text-xs text-red-400">{j.error}</p>}
            {j.status === "done" && (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span
                  className={`text-xs ${
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
                </span>
                {j.library_confirmed === false && (
                  <button
                    className="btn-ghost px-2 py-0.5 text-xs"
                    title="Volver a comprobar en Navidrome"
                    onClick={() => recheck(j.id)}
                  >
                    ↻ Re-comprobar
                  </button>
                )}
              </div>
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
