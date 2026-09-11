import { useCallback, useEffect, useRef, useState } from "react";
import { COLLECTION_EVENT } from "./useEvents";

export function collectionChanged() { window.dispatchEvent(new Event(COLLECTION_EVENT)); }

/** Refetch shared state after reconnect/mutations, ignoring responses for older queries. */
export function useCollection<T>(load: () => Promise<T>, keys: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loader = useRef(load);
  loader.current = load;
  const sequence = useRef(0);
  const reload = useCallback(() => {
    const request = ++sequence.current;
    setLoading(true);
    void loader.current().then(result => {
      if (sequence.current === request) { setData(result); setError(null); }
    }).catch(e => {
      if (sequence.current === request) setError((e as Error).message);
    }).finally(() => { if (sequence.current === request) setLoading(false); });
  }, []);
  useEffect(() => {
    setData(null);
    reload();
    window.addEventListener(COLLECTION_EVENT, reload);
    window.addEventListener("focus", reload);
    const timer = window.setInterval(() => { if (!document.hidden) reload(); }, 15000);
    return () => {
      ++sequence.current;
      clearInterval(timer);
      window.removeEventListener(COLLECTION_EVENT, reload);
      window.removeEventListener("focus", reload);
    };
  }, [reload, ...keys]);
  return {data, error, loading, reload};
}
