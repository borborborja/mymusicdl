import type {
  AlbumDetail,
  BotStatus,
  DownloadItemInput,
  Job,
  SearchResponse,
  SettingsData,
  Tool,
} from "./types";

const PW_KEY = "mymusicdl_pw";

export function getStoredPassword(): string {
  return localStorage.getItem(PW_KEY) ?? "";
}
export function setStoredPassword(pw: string): void {
  if (pw) localStorage.setItem(PW_KEY, pw);
  else localStorage.removeItem(PW_KEY);
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) };
  const pw = getStoredPassword();
  if (pw) headers["X-App-Password"] = pw;
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

  const res = await fetch(`/api${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

export interface SearchParams {
  q: string;
  kind: "song" | "album" | "artist";
  providers?: string[];
  losslessOnly?: boolean;
  limit?: number;
}

export const api = {
  health: () => req<Record<string, unknown>>("/health"),

  search: ({ q, kind, providers, losslessOnly, limit }: SearchParams) => {
    const p = new URLSearchParams({ q, kind });
    if (providers?.length) p.set("providers", providers.join(","));
    if (losslessOnly) p.set("lossless_only", "true");
    if (limit) p.set("limit", String(limit));
    return req<SearchResponse>(`/search?${p.toString()}`);
  },

  album: (provider: string, id: string) =>
    req<AlbumDetail>(`/album/${encodeURIComponent(provider)}/${encodeURIComponent(id)}`),

  enqueue: (items: DownloadItemInput[]) =>
    req<Job[]>("/downloads", { method: "POST", body: JSON.stringify({ items }) }),

  listJobs: () => req<Job[]>("/jobs?limit=200"),
  cancelJob: (id: string) => req<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  retryJob: (id: string) => req<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  recheckJob: (id: string) => req<Job>(`/jobs/${id}/recheck`, { method: "POST" }),
  deleteJob: (id: string) => req<{ deleted: string }>(`/jobs/${id}`, { method: "DELETE" }),
  clearJobs: () => req<{ deleted: number }>("/jobs/clear", { method: "POST" }),

  tools: () => req<Tool[]>("/tools"),
  checkTools: () => req<{ status: string }>("/tools/check", { method: "POST" }),
  updateTool: (name: string) => req<Job>(`/tools/${encodeURIComponent(name)}/update`, { method: "POST" }),

  settings: () => req<SettingsData>("/settings"),
  setCredential: (provider: string, data: Record<string, string>) =>
    req<unknown>(`/settings/credentials/${provider}`, {
      method: "PUT",
      body: JSON.stringify({ data }),
    }),
  deleteCredential: (provider: string) =>
    req<unknown>(`/settings/credentials/${provider}`, { method: "DELETE" }),
  setConcurrency: (value: number) =>
    req<{ download_concurrency: number }>("/settings/concurrency", {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  setLayout: (template: string) =>
    req<{ download_layout: string }>("/settings/layout", {
      method: "PUT",
      body: JSON.stringify({ template }),
    }),

  libraryItems: () => req<unknown[]>("/library/items"),
  rescan: () => req<unknown>("/library/rescan", { method: "POST" }),

  bots: () => req<BotStatus[]>("/bots"),
  setBot: (name: string, data: Record<string, string>) =>
    req<{ ok: boolean; status: BotStatus | null }>(`/bots/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ data }),
    }),
  deleteBot: (name: string) =>
    req<{ ok: boolean }>(`/bots/${encodeURIComponent(name)}`, { method: "DELETE" }),
};
