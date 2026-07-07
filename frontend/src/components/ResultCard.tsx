import { Link } from "react-router-dom";

import type { AlbumResult, ArtistResult } from "../lib/types";
import Artwork from "./Artwork";

export function AlbumCard({ album }: { album: AlbumResult }) {
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
