import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

interface ConfirmOptions {
  title: string;
  body?: string;
  confirmLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmCtx = createContext<ConfirmFn | null>(null);

/** Provides a promise-based confirm() for destructive actions, rendered as an accessible modal. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((options) => {
    setOpts(options);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const close = useCallback((value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setOpts(null);
  }, []);

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmCtx.Provider value={value}>
      {children}
      {opts && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={opts.title}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => close(false)}
        >
          <div
            className="card w-full max-w-sm space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-base font-semibold">{opts.title}</h2>
            {opts.body && <p className="text-sm text-slate-400">{opts.body}</p>}
            <div className="flex justify-end gap-2">
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => close(false)} autoFocus>
                Cancelar
              </button>
              <button
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                  opts.danger
                    ? "bg-red-600 text-white hover:bg-red-500"
                    : "btn-primary"
                }`}
                onClick={() => close(true)}
              >
                {opts.confirmLabel ?? "Aceptar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmCtx);
  if (!ctx) throw new Error("useConfirm must be used within a ConfirmProvider");
  return ctx;
}
