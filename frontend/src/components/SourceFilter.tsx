import type { ProviderInfo } from "../lib/types";

export default function SourceFilter({
  providers,
  selected,
  onSelected,
  losslessOnly,
  onLossless,
}: {
  providers: ProviderInfo[];
  selected: string[];
  onSelected: (next: string[]) => void;
  losslessOnly: boolean;
  onLossless: (v: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-slate-500">Fuentes</span>
      {providers.map((p) => {
        const on = selected.includes(p.id);
        return (
          <button
            key={p.id}
            type="button"
            disabled={!p.enabled}
            title={p.enabled ? undefined : "Sin credenciales — actívala en Ajustes"}
            onClick={() => onSelected(on ? selected.filter((x) => x !== p.id) : [...selected, p.id])}
            className={`chip border ${
              on
                ? "border-brand bg-brand text-slate-950"
                : "border-slate-700 text-slate-300 hover:bg-slate-800"
            } ${!p.enabled ? "opacity-40" : ""}`}
          >
            {p.label}
          </button>
        );
      })}
      <label className="ml-2 flex items-center gap-1.5 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={losslessOnly}
          onChange={(e) => onLossless(e.target.checked)}
        />
        Solo lossless
      </label>
    </div>
  );
}
