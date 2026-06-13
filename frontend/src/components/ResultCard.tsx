import { Link } from "react-router-dom";

import type { AlbumResult, ArtistResult } from "../lib/types";

export function AlbumCard({ album }: { album: AlbumResult }) {
  return (
    <Link
      to={`/album/${encodeURIComponent(album.provider)}/${encodeURIComponent(album.id)}`}
      className="card flex gap-3 hover:border-slate-600"
    >
      {album.cover_url ? (
        <img src={album.cover_url} alt="" className="h-16 w-16 rounded object-cover" />
      ) : (
        <div className="h-16 w-16 rounded bg-slate-800" />
      )}
      <div className="min-w-0">
        <div className="truncate font-medium">{album.title}</div>
        <div className="truncate text-sm text-slate-400">
          {album.artist}
          {album.year ? ` · ${album.year}` : ""}
        </div>
        {album.total_tracks ? (
          <div className="text-xs text-slate-500">{album.total_tracks} pistas</div>
        ) : null}
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
      className="card flex items-center gap-3 text-left hover:border-slate-600"
    >
      {artist.cover_url ? (
        <img src={artist.cover_url} alt="" className="h-16 w-16 rounded-full object-cover" />
      ) : (
        <div className="h-16 w-16 rounded-full bg-slate-800" />
      )}
      <div className="truncate font-medium">{artist.name}</div>
    </button>
  );
}
