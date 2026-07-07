import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import type { AlbumResult, ArtistResult, DownloadItemInput } from "../lib/types";
import { bestOption, toTrackPayload } from "../lib/util";
import Artwork from "./Artwork";

export function AlbumCard({
  album,
  onEnqueued,
}: {
  album: AlbumResult;
  onEnqueued?: (message: string) => void;
}) {
  // Queues every track of the album individually (same as select-all on the album page) —
  // still no whole-album blobs, just a shortcut past the detail view.
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");

  const downloadAll = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (state !== "idle") return;
    setState("busy");
    try {
      const detail = await api.album(album.provider, album.id);
      const items = detail.tracks
        .map((t): DownloadItemInput | null => {
          const opt = bestOption(t);
          return opt ? { provider: opt.provider, quality: opt.tier, track: toTrackPayload(t) } : null;
        })
        .filter((x): x is DownloadItemInput => x !== null);
      if (!items.length) {
        onEnqueued?.(`"${album.title}" no tiene fuentes disponibles.`);
        setState("idle");
        return;
      }
      const jobs = await api.enqueue(items);
      onEnqueued?.(`${jobs.length} canción(es) de "${album.title}" en la cola.`);
      setState("done");
    } catch (err) {
      onEnqueued?.((err as Error).message);
      setState("idle");
    }
  };

  return (
    <Link
      to={`/album/${encodeURIComponent(album.provider)}/${encodeURIComponent(album.id)}`}
      className="group block"
    >
      <div className="relative">
        <Artwork
          src={album.cover_url}
          alt={album.title}
          seed={`${album.title} ${album.artist}`}
          rounded="rounded-xl"
          className="aspect-square w-full shadow-lg ring-1 ring-slate-800 transition group-hover:ring-2 group-hover:ring-brand/70"
        />
        {album.total_tracks ? (
          <span className="absolute right-2 top-2 rounded-full bg-black/65 px-2 py-0.5 text-[11px] font-medium text-white/90 backdrop-blur-sm">
            {album.total_tracks}
          </span>
        ) : null}
        <button
          type="button"
          onClick={downloadAll}
          disabled={state !== "idle"}
          title={state === "done" ? "En la cola" : "Descargar el álbum (pista a pista)"}
          className="absolute bottom-2 right-2 flex h-9 w-9 items-center justify-center rounded-full bg-black/65 text-lg text-white/90 backdrop-blur-sm transition hover:bg-brand hover:text-slate-950 disabled:hover:bg-black/65 disabled:hover:text-white/90"
        >
          {state === "busy" ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
          ) : state === "done" ? (
            "✓"
          ) : (
            "↓"
          )}
        </button>
      </div>
      <div className="mt-2 min-w-0">
        <div className="truncate font-medium text-slate-100 group-hover:text-brand">
          {album.title}
        </div>
        <div className="truncate text-sm text-slate-400">
          {album.artist}
          {album.year ? ` · ${album.year}` : ""}
        </div>
      </div>
    </Link>
  );
}

export function ArtistCard({
  artist,
  onPick,
}: {
  artist: ArtistResult;
  onPick: (name: string) => void;
}) {
  return (
    <button
      onClick={() => onPick(artist.name)}
      className="group flex flex-col items-center gap-2 text-center"
      title={`Ver álbumes de ${artist.name}`}
    >
      <Artwork
        src={artist.cover_url}
        alt={artist.name}
        seed={artist.name}
        rounded="rounded-full"
        className="aspect-square w-full shadow-lg ring-1 ring-slate-800 transition group-hover:ring-2 group-hover:ring-brand/70"
      />
      <div className="w-full truncate text-sm font-medium text-slate-200 group-hover:text-brand">
        {artist.name}
      </div>
    </button>
  );
}
