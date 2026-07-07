import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

type ToastKind = "info" | "success" | "error";
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}

interface ToastApi {
  show: (text: string, kind?: ToastKind) => void;
  success: (text: string) => void;
  error: (text: string) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

const STYLE: Record<ToastKind, string> = {
  info: "border-slate-600 bg-slate-800 text-slate-100",
  success: "border-emerald-600/60 bg-emerald-950/80 text-emerald-100",
  error: "border-red-600/60 bg-red-950/80 text-red-100",
};

/** App-wide toast provider. Toasts auto-dismiss and are announced via an aria-live region. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const remove = useCallback((id: number) => {
    setToasts((ts) => ts.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (text: string, kind: ToastKind = "info") => {
      const id = nextId.current++;
      setToasts((ts) => [...ts, { id, kind, text }]);
      setTimeout(() => remove(id), kind === "error" ? 6000 : 4000);
    },
    [remove],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (t: string) => show(t, "success"),
      error: (t: string) => show(t, "error"),
    }),
    [show],
  );

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-3"
      >
        {toasts.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => remove(t.id)}
            className={`pointer-events-auto max-w-md rounded-lg border px-4 py-2 text-sm shadow-lg ${STYLE[t.kind]}`}
          >
            {t.text}
          </button>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
