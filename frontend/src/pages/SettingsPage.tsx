import { useEffect, useState } from "react";

import { api, getStoredPassword, setStoredPassword } from "../lib/api";
import type { SettingsData } from "../lib/types";

const CRED_FIELD: Record<string, { key: string; placeholder: string }> = {
  tidal: { key: "token", placeholder: "access token de Tidal" },
  qobuz: { key: "token", placeholder: "auth token de Qobuz" },
  deezer: { key: "arl", placeholder: "cookie ARL de Deezer" },
};

export default function SettingsPage() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [pw, setPw] = useState(getStoredPassword());
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    api.settings().then(setData).catch(() => undefined);
  };
  useEffect(load, []);

  const save = async (provider: string) => {
    const field = CRED_FIELD[provider];
    const val = inputs[provider]?.trim();
    if (!field || !val) return;
    try {
      await api.setCredential(provider, { [field.key]: val });
      setMsg(`${provider} activado.`);
      setInputs((p) => ({ ...p, [provider]: "" }));
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const disable = async (provider: string) => {
    try {
      await api.deleteCredential(provider);
      setMsg(`${provider} desactivado.`);
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const savePw = () => {
    setStoredPassword(pw);
    setMsg("Contraseña guardada en este navegador.");
  };

  const paid = data?.providers.filter((p) => p.requires_credentials) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold">Ajustes</h1>
        {data && (
          <p className="text-sm text-slate-400">
            Catálogo activo: <span className="text-slate-200">{data.metadata}</span>
          </p>
        )}
      </div>

      {msg && (
        <div className="rounded-md border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm">
          {msg}
        </div>
      )}

      <section className="card">
        <h2 className="mb-2 font-medium">Fuentes de pago</h2>
        <p className="mb-3 text-sm text-slate-400">
          Añade credenciales para activar Tidal, Qobuz o Deezer (lossless/hi-res vía streamrip). Sin
          credenciales permanecen ocultas en la búsqueda.
        </p>
        <div className="space-y-3">
          {paid.map((p) => {
            const field = CRED_FIELD[p.id];
            return (
              <div key={p.id} className="flex flex-wrap items-center gap-2">
                <span className="flex w-44 items-center gap-2 text-sm">
                  {p.label}
                  {p.enabled ? (
                    <span className="chip border border-emerald-600/30 bg-emerald-500/15 text-emerald-300">
                      activa
                    </span>
                  ) : (
                    <span className="chip border border-slate-700 text-slate-400">inactiva</span>
                  )}
                </span>
                {field ? (
                  <input
                    className="input flex-1"
                    placeholder={field.placeholder}
                    value={inputs[p.id] ?? ""}
                    onChange={(e) => setInputs((s) => ({ ...s, [p.id]: e.target.value }))}
                  />
                ) : (
                  <span className="flex-1 text-xs text-slate-500">no configurable aquí</span>
                )}
                <button className="btn-primary" onClick={() => save(p.id)} disabled={!field}>
                  Guardar
                </button>
                {p.enabled && (
                  <button className="btn-ghost" onClick={() => disable(p.id)}>
                    Desactivar
                  </button>
                )}
              </div>
            );
          })}
          {paid.length === 0 && (
            <p className="text-sm text-slate-500">No hay proveedores de pago registrados.</p>
          )}
        </div>
      </section>

      <section className="card">
        <h2 className="mb-2 font-medium">Contraseña compartida (opcional)</h2>
        <p className="mb-3 text-sm text-slate-400">
          Solo necesaria si has definido <code>APP_SHARED_PASSWORD</code>. Se guarda en este navegador
          y se envía como cabecera <code>X-App-Password</code>.
        </p>
        <div className="flex gap-2">
          <input
            className="input flex-1"
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            placeholder="contraseña"
          />
          <button className="btn-primary" onClick={savePw}>
            Guardar
          </button>
        </div>
      </section>
    </div>
  );
}
