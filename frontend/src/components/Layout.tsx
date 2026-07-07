import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { useJobs } from "../store/jobs";

const tabs = [
  { to: "/", label: "Buscar", end: true },
  { to: "/library", label: "Biblioteca" },
  { to: "/queue", label: "Descargas" },
  { to: "/tools", label: "Herramientas" },
  { to: "/settings", label: "Ajustes" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const jobs = useJobs();
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued").length;

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-3 py-3 sm:px-4">
          <div className="flex shrink-0 items-center gap-2 text-base font-semibold sm:text-lg">
            <span aria-hidden>🎵</span>
            <span>mymusicdl</span>
          </div>
          <nav className="flex min-w-0 flex-1 items-center justify-end gap-0.5 overflow-x-auto whitespace-nowrap sm:gap-1">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  `relative shrink-0 rounded-md px-2 py-1.5 text-xs font-medium transition-colors sm:px-3 sm:text-sm ${
                    isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800/60"
                  }`
                }
              >
                {t.label}
                {t.to === "/queue" && active > 0 && (
                  <span className="ml-1 rounded-full bg-brand px-1.5 text-xs font-semibold text-slate-950">
                    {active}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-3 py-5 sm:px-4 sm:py-6">{children}</main>
    </div>
  );
}
