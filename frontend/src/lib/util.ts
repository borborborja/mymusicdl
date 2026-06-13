import type { DownloadItemInput, TrackResult } from "./types";

export function formatDuration(s?: number | null): string {
  if (!s) return "";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export interface FlatOption {
  value: string;
  label: string;
  provider: string;
  tier: number;
}

export function flattenOptions(track: TrackResult): FlatOption[] {
  const out: FlatOption[] = [];
  for (const p of track.providers) {
    for (const q of p.qualities) {
      out.push({
        value: `${p.provider}:${q.tier}`,
        label: `${p.label} · ${q.label}`,
        provider: p.provider,
        tier: q.tier,
      });
    }
  }
  return out;
}

export function bestOption(track: TrackResult): FlatOption | undefined {
  const opts = flattenOptions(track);
  if (!opts.length) return undefined;
  return opts.reduce((a, b) => (b.tier > a.tier ? b : a));
}

export function toTrackPayload(t: TrackResult): DownloadItemInput["track"] {
  return {
    title: t.title,
    artist: t.artist,
    album: t.album ?? null,
    source_url: t.source_url ?? null,
    isrc: t.isrc ?? null,
    duration_s: t.duration_s ?? null,
    cover_url: t.cover_url ?? null,
    ext_ids: t.ext_ids ?? {},
  };
}
