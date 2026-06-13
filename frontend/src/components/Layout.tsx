import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { useJobs } from "../store/jobs";

const tabs = [
  { to: "/", label: "Buscar", end: true },
  { to: "/queue", label: "Descargas" },
  { to: "/tools", label: "Herramientas" },
  { to: "/settings", label: "Ajustes" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const jobs = useJobs();
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued").length;

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <span aria-hidden>🎵</span> mymusicdl
          </div>
          <nav className="flex items-center gap-1">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  `relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
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
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}
