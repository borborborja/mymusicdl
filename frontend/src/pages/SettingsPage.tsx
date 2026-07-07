import { useEffect, useState } from "react";

import { api, getStoredPassword, setStoredPassword } from "../lib/api";
import type { BotStatus, SettingsData } from "../lib/types";

const CRED_FIELD: Record<string, { key: string; placeholder: string }> = {
  tidal: { key: "token", placeholder: "access token de Tidal" },
  qobuz: { key: "token", placeholder: "auth token de Qobuz" },
  deezer: { key: "arl", placeholder: "cookie ARL de Deezer" },
};

const BOT_LABEL: Record<string, string> = { telegram: "Telegram", matrix: "Matrix" };

const LAYOUT_PRESETS: { label: string; value: string }[] = [
  { label: "Artista / Álbum / Canción", value: "{artist}/{album}/{title}" },
  { label: "Artista / Canción", value: "{artist}/{title}" },
  { label: "Plano (Artista - Canción)", value: "{artist} - {title}" },
];

const layoutExample = (tpl: string): string =>
  tpl
    .split("{artist}")
    .join("Daft Punk")
    .split("{album}")
    .join("Discovery")
    .split("{title}")
    .join("One More Time")
    .split("{year}")
    .join("2001") + ".mp3";

const BOT_FIELDS: Record<
  string,
  { key: string; label: string; placeholder: string; type?: string }[]
> = {
  telegram: [
    { key: "token", label: "Bot token", placeholder: "123456:ABC… (de @BotFather)", type: "password" },
    { key: "allowed_users", label: "IDs permitidos", placeholder: "111111111, 222222222" },
  ],
  matrix: [
    { key: "homeserver", label: "Homeserver", placeholder: "https://matrix.org" },
    { key: "user_id", label: "User ID del bot", placeholder: "@musicbot:matrix.org" },
    { key: "access_token", label: "Access token", placeholder: "token de acceso", type: "password" },
    { key: "allowed_users", label: "Usuarios permitidos", placeholder: "@tu:matrix.org, @otro:matrix.org" },
    { key: "room_id", label: "Room ID (opcional)", placeholder: "!sala:matrix.org" },
  ],
};

function StatusChip({ bot }: { bot: BotStatus }) {
  if (!bot.configured) {
    return <span className="chip border border-slate-700 text-slate-400">desactivado</span>;
  }
  if (bot.running && bot.connected) {
    return (
      <span className="chip border border-emerald-600/30 bg-emerald-500/15 text-emerald-300">
        ● conectado
      </span>
    );
  }
  if (bot.error) {
    return (
      <span
        title={bot.error}
        className="chip border border-red-600/30 bg-red-500/15 text-red-300"
      >
        error
      </span>
    );
  }
  return (
    <span className="chip border border-amber-600/30 bg-amber-500/15 text-amber-300">
      configurado
    </span>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [bots, setBots] = useState<BotStatus[]>([]);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [botInputs, setBotInputs] = useState<Record<string, Record<string, string>>>({});
  const [pw, setPw] = useState(getStoredPassword());
  const [msg, setMsg] = useState<string | null>(null);
  const [spotify, setSpotify] = useState({ client_id: "", client_secret: "" });
  const [concurrency, setConcurrency] = useState(2);
  const [layout, setLayout] = useState("{artist}/{album}/{title}");

  const load = () => {
    api
      .settings()
      .then((s) => {
        setData(s);
        setConcurrency(s.download_concurrency);
        setLayout(s.download_layout);
      })
      .catch(() => undefined);
    api.bots().then(setBots).catch(() => undefined);
  };
  useEffect(load, []);

  const saveSpotify = async () => {
    const cid = spotify.client_id.trim();
    const secret = spotify.client_secret.trim();
    if (!cid || !secret) {
      setMsg("Introduce Client ID y Client Secret de Spotify.");
      return;
    }
    try {
      await api.setCredential("spotify", { client_id: cid, client_secret: secret });
      setMsg("Spotify activado como catálogo.");
      setSpotify({ client_id: "", client_secret: "" });
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const disableSpotify = async () => {
    try {
      await api.deleteCredential("spotify");
      setMsg("Spotify desactivado (se usará MusicBrainz).");
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const saveConcurrency = async () => {
    try {
      const r = await api.setConcurrency(concurrency);
      setConcurrency(r.download_concurrency);
      setMsg(`Descargas simultáneas: ${r.download_concurrency}.`);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const saveLayout = async () => {
    try {
      const r = await api.setLayout(layout);
      setLayout(r.download_layout);
      setMsg("Estructura de carpetas guardada.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

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

  const saveBot = async (name: string) => {
    const fields = botInputs[name] ?? {};
    const data = Object.fromEntries(
      Object.entries(fields).filter(([, v]) => v && v.trim()).map(([k, v]) => [k, v.trim()]),
    );
    if (!Object.keys(data).length) {
      setMsg("Rellena al menos un campo del bot.");
      return;
    }
    try {
      await api.setBot(name, data);
      setMsg(`${BOT_LABEL[name] ?? name} guardado.`);
      setBotInputs((p) => ({ ...p, [name]: {} }));
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const disableBot = async (name: string) => {
    try {
      await api.deleteBot(name);
      setMsg(`${BOT_LABEL[name] ?? name} desactivado.`);
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const setBotField = (name: string, key: string, value: string) =>
    setBotInputs((p) => ({ ...p, [name]: { ...(p[name] ?? {}), [key]: value } }));

  const paid = data?.providers.filter((p) => p.requires_credentials) ?? [];
  const spotifyCred = data?.credentials.find((c) => c.provider === "spotify");
  const spotifyActive = !!spotifyCred?.enabled || data?.metadata === "spotify";

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
        <h2 className="mb-2 flex items-center gap-2 font-medium">
          Catálogo (Spotify)
          {spotifyActive ? (
            <span className="chip border border-emerald-600/30 bg-emerald-500/15 text-emerald-300">
              activo
            </span>
          ) : (
            <span className="chip border border-slate-700 text-slate-400">MusicBrainz</span>
          )}
        </h2>
        <p className="mb-3 text-sm text-slate-400">
          Añade credenciales de Spotify (client-credentials) para fotos de artista, mejores
          coincidencias y menos duplicados. Créalas en{" "}
          <a
            className="text-brand hover:underline"
            href="https://developer.spotify.com/dashboard"
            target="_blank"
            rel="noreferrer"
          >
            developer.spotify.com
          </a>
          . Sin esto se usa MusicBrainz.
        </p>
        <div className="space-y-2">
          <input
            className="input w-full"
            placeholder="Client ID"
            value={spotify.client_id}
            onChange={(e) => setSpotify((s) => ({ ...s, client_id: e.target.value }))}
          />
          <input
            className="input w-full"
            type="password"
            placeholder="Client Secret"
            value={spotify.client_secret}
            onChange={(e) => setSpotify((s) => ({ ...s, client_secret: e.target.value }))}
          />
          <div className="flex gap-2">
            <button className="btn-primary" onClick={saveSpotify}>
              Guardar y activar
            </button>
            {spotifyCred?.enabled && (
              <button className="btn-ghost" onClick={disableSpotify}>
                Desactivar
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="card">
        <h2 className="mb-2 font-medium">Descargas simultáneas</h2>
        <p className="mb-3 text-sm text-slate-400">
          Cuántas canciones se descargan a la vez. El cambio se aplica al instante, sin reiniciar.
        </p>
        <div className="flex items-center gap-2">
          <input
            className="input w-24"
            type="number"
            min={1}
            max={16}
            value={concurrency}
            onChange={(e) => setConcurrency(Number(e.target.value))}
          />
          <button className="btn-primary" onClick={saveConcurrency}>
            Guardar
          </button>
        </div>
      </section>

      <section className="card">
        <h2 className="mb-2 font-medium">Carpeta de descarga</h2>
        <p className="mb-3 text-sm text-slate-400">
          Estructura dentro de la biblioteca de Navidrome
          {data?.music_library_path ? (
            <>
              {" "}(<code>{data.music_library_path}</code>)
            </>
          ) : null}
          . Tokens disponibles: <code>{"{artist}"}</code> <code>{"{album}"}</code>{" "}
          <code>{"{title}"}</code> <code>{"{year}"}</code>.
        </p>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {LAYOUT_PRESETS.map((p) => (
              <button
                key={p.value}
                type="button"
                className={`chip border ${
                  layout === p.value
                    ? "border-brand bg-brand/15 text-brand"
                    : "border-slate-700 text-slate-300 hover:text-white"
                }`}
                onClick={() => setLayout(p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <input
            className="input w-full font-mono text-sm"
            value={layout}
            onChange={(e) => setLayout(e.target.value)}
            placeholder="{artist}/{album}/{title}"
          />
          <p className="text-xs text-slate-500">
            Ejemplo: <code>{layoutExample(layout)}</code>
          </p>
          <button className="btn-primary" onClick={saveLayout}>
            Guardar
          </button>
        </div>
      </section>

      <section className="card">
        <h2 className="mb-2 font-medium">Bots de mensajería</h2>
        <p className="mb-3 text-sm text-slate-400">
          Misma funcionalidad que la web, por chat: busca y descarga enviando mensajes. Solo los IDs
          de la allowlist pueden usarlo. Las descargas hechas por un bot se marcan con 📱 en la cola.
        </p>
        <div className="space-y-4">
          {bots.map((bot) => {
            const fromEnv = bot.source === "env";
            return (
              <div key={bot.name} className="rounded-lg border border-slate-800 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{BOT_LABEL[bot.name] ?? bot.name}</span>
                  <StatusChip bot={bot} />
                  {bot.identity && (
                    <span className="text-xs text-slate-400">{bot.identity}</span>
                  )}
                  {bot.configured && (
                    <span className="text-xs text-slate-500">
                      · {bot.allowed_count} permitido(s) · vía {bot.source}
                    </span>
                  )}
                </div>

                {bot.error && (
                  <p className="mt-2 wrap-break-word text-xs text-red-400">{bot.error}</p>
                )}

                {fromEnv ? (
                  <p className="mt-2 text-xs text-slate-500">
                    Configurado mediante variables de entorno (.env). Edítalo allí para cambiarlo.
                  </p>
                ) : (
                  <div className="mt-3 space-y-2">
                    {BOT_FIELDS[bot.name]?.map((f) => (
                      <div key={f.key} className="flex flex-wrap items-center gap-2">
                        <label className="w-36 text-sm text-slate-300">{f.label}</label>
                        <input
                          className="input flex-1"
                          type={f.type ?? "text"}
                          placeholder={f.placeholder}
                          value={botInputs[bot.name]?.[f.key] ?? ""}
                          onChange={(e) => setBotField(bot.name, f.key, e.target.value)}
                        />
                      </div>
                    ))}
                    <div className="flex gap-2 pt-1">
                      <button className="btn-primary" onClick={() => saveBot(bot.name)}>
                        Guardar y conectar
                      </button>
                      {bot.configured && (
                        <button className="btn-ghost" onClick={() => disableBot(bot.name)}>
                          Desactivar
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {bots.length === 0 && <p className="text-sm text-slate-500">No hay bots disponibles.</p>}
        </div>
      </section>

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
          <button
            className="btn-primary"
            onClick={() => {
              setStoredPassword(pw);
              setMsg("Contraseña guardada en este navegador.");
            }}
          >
            Guardar
          </button>
        </div>
      </section>
    </div>
  );
}
