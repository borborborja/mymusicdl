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
          upsertJob(data.job);
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
