import { useEffect } from "react";

import { upsertJob } from "../store/jobs";

export const TOOLS_EVENT = "mymusicdl:tools";

/** Opens the single SSE stream and routes events into the jobs store. Mount once (in App). */
export function useEventStream() {
  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onmessage = (e) => {
      if (!e.data) return;
      try {
        const data = JSON.parse(e.data);
        if (data.type === "job" && data.job) {
          // The live event carries transient speed/eta alongside the job DTO — merge them in so the
          // queue can show throughput while a download runs.
          const extra: Record<string, unknown> = {};
          if (data.speed != null) extra.speed = data.speed;
          if (data.eta_s != null) extra.eta_s = data.eta_s;
          upsertJob({ ...data.job, ...extra });
        } else if (data.type === "tools") {
          window.dispatchEvent(new CustomEvent(TOOLS_EVENT));
        }
      } catch {
        /* keep-alive comment or malformed payload — ignore */
      }
    };
    es.onerror = () => {
      /* EventSource reconnects automatically */
    };
    return () => es.close();
  }, []);
}
