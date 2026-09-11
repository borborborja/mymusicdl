import { useEffect } from "react";

import { upsertJob } from "../store/jobs";
import { api } from "./api";

export const COLLECTION_EVENT = "mymusicdl:collection";
export const TOOLS_EVENT = "mymusicdl:tools";

/** Opens the single SSE stream and routes events into the jobs store. Mount once (in App). */
export function useEventStream() {
  useEffect(() => {
    let active = true;
    const es = new EventSource("/api/events");
    es.onopen = () => {
      window.dispatchEvent(new Event(COLLECTION_EVENT));
      // The broker does not replay events missed while disconnected. Recover the
      // persisted state on each connection, merging so newer live events win.
      void api.listJobs().then((jobs) => {
        if (active) jobs.forEach(upsertJob);
      }).catch(() => {
        // A failed snapshot must not interrupt live updates or automatic reconnects.
      });
    };
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
          if (data.job.status === "done" || data.job.status === "error" || data.job.status === "canceled") window.dispatchEvent(new Event(COLLECTION_EVENT));
        } else if (data.type === "collection") {
          window.dispatchEvent(new Event(COLLECTION_EVENT));
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
    return () => {
      active = false;
      es.close();
    };
  }, []);
}
