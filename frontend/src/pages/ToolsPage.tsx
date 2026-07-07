import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { Tool } from "../lib/types";
import { TOOLS_EVENT } from "../lib/useEvents";

export default function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [checking, setChecking] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    api.tools().then(setTools).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const handler = () => load();
    window.addEventListener(TOOLS_EVENT, handler);
    return () => window.removeEventListener(TOOLS_EVENT, handler);
  }, [load]);

  const check = async () => {
    setChecking(true);
    setMsg(null);
    try {
      await api.checkTools();
      setMsg("Comprobación lanzada — los datos se refrescan en unos segundos.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  const update = async (name: string) => {
    try {
      await api.updateTool(name);
      setMsg(`Actualizando ${name}… sigue el progreso en Descargas.`);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Herramientas de descarga</h1>
        <button className="btn-ghost" disabled={checking} onClick={check}>
          Buscar actualizaciones
        </button>
      </div>

      {msg && (
        <div className="mb-3 rounded-md border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm">
          {msg}
        </div>
      )}

      {tools.length === 0 && (
        <p className="text-slate-500">Sin datos todavía. Pulsa «Buscar actualizaciones».</p>
      )}

      <div className="space-y-3">
        {tools.map((t) => (
          <div key={t.name} className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="font-medium">
                  {t.name}
                  {t.update_available && (
                    <span className="chip ml-2 border border-amber-600/40 bg-amber-500/15 text-amber-300">
                      actualización
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500">
                  instalada {t.installed_version ?? "—"} · última {t.latest_version ?? "—"}
                  {t.latest_tag ? ` (${t.latest_tag})` : ""}
                </div>
              </div>
              <button
                className="btn-primary"
                disabled={!t.update_available || !t.managed}
                onClick={() => update(t.name)}
              >
                Actualizar
              </button>
            </div>
            {t.changelog && (
              <details className="mt-2">
                <summary className="cursor-pointer text-sm text-slate-400">Changelog</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-sm bg-slate-950 p-3 text-xs text-slate-300">
                  {t.changelog}
                </pre>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
