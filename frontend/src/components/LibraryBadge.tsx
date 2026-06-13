import type { LibraryMatch } from "../lib/types";

export default function LibraryBadge({ library }: { library: LibraryMatch }) {
  if (!library.in_library) {
    return (
      <span className="chip border border-slate-700 bg-slate-800 text-slate-400">No descargada</span>
    );
  }
  return (
    <span className="chip border border-sky-600/30 bg-sky-500/15 text-sky-300">
      En biblioteca{library.quality ? ` · ${library.quality.label}` : ""}
      {library.can_upgrade ? " · ⬆ mejorable" : ""}
    </span>
  );
}
