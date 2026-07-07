import { useSyncExternalStore } from "react";

// One shared <audio> so only a single preview plays at a time. State is exposed via
// useSyncExternalStore so buttons reflect loading/playing without prop-drilling.
type Status = "idle" | "loading" | "playing";
interface PreviewState {
  key: string | null;
  status: Status;
}

let state: PreviewState = { key: null, status: "idle" };
const listeners = new Set<() => void>();
let audio: HTMLAudioElement | null = null;

function set(next: PreviewState) {
  state = next;
  listeners.forEach((l) => l());
}

function ensureAudio(): HTMLAudioElement {
  if (!audio) {
    audio = new Audio();
    audio.onended = () => set({ key: null, status: "idle" });
    audio.onerror = () => set({ key: null, status: "idle" });
  }
  return audio;
}

/** Toggle preview for `key`: stops if it's the one playing, else resolves the URL and plays it. */
export async function togglePreview(key: string, resolveUrl: () => Promise<string>): Promise<void> {
  const a = ensureAudio();
  if (state.key === key && state.status !== "idle") {
    a.pause();
    set({ key: null, status: "idle" });
    return;
  }
  a.pause();
  set({ key, status: "loading" });
  try {
    const url = await resolveUrl();
    if (state.key !== key) return; // superseded by another click
    a.src = url;
    await a.play();
    if (state.key === key) set({ key, status: "playing" });
  } catch (e) {
    if (state.key === key) set({ key: null, status: "idle" });
    throw e;
  }
}

export function usePreview(): PreviewState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}
