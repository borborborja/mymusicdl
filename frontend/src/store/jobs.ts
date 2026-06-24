import { useSyncExternalStore } from "react";

import type { Job } from "../lib/types";

const jobs = new Map<string, Job>();
const listeners = new Set<() => void>();
let snapshot: Job[] = [];

function rebuild() {
  snapshot = Array.from(jobs.values()).sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  );
  listeners.forEach((l) => l());
}

export function upsertJob(job: Job) {
  jobs.set(job.id, { ...jobs.get(job.id), ...job });
  rebuild();
}

export function setJobs(list: Job[]) {
  jobs.clear();
  list.forEach((j) => jobs.set(j.id, j));
  rebuild();
}

export function removeJob(id: string) {
  if (jobs.delete(id)) rebuild();
}

export function removeFinished() {
  let changed = false;
  for (const [id, j] of jobs) {
    if (j.status === "done" || j.status === "error" || j.status === "canceled") {
      jobs.delete(id);
      changed = true;
    }
  }
  if (changed) rebuild();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot() {
  return snapshot;
}

export function useJobs(): Job[] {
  return useSyncExternalStore(subscribe, getSnapshot);
}
