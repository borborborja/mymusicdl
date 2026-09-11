// Run against Vite; see docs/VERIFICATION.md. Playwright is a test-only dependency.
import assert from "node:assert/strict";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  headless: true,
  args: ["--no-sandbox"],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
let confirmed = false;
await page.addInitScript(() => {
  window.EventSource = class {
    constructor() { window.testStream = this; }
    close() {}
  };
});
await page.route("**/api/**", (route) => {
  const path = new URL(route.request().url()).pathname;
  const job = {
    id: "reconnect", kind: "download", provider: "ytdlp", status: "done",
    progress_pct: 100, title: "Reconnect Song",
    library_status: confirmed ? "confirmed" : "pending",
    library_confirmed: confirmed,
    updated_at: confirmed ? "2026-09-11T10:00:02" : "2026-09-11T10:00:01",
  };
  return route.fulfill({ json: path === "/api/jobs" ? [job] : path === "/api/health" ? {
    app: "ok", db_ok: true, queue: { workers: 2, active: 0, queued: 0, running: 0 },
  } : [] });
});
try {
  await page.goto((process.env.CHECK_BASE_URL || "http://127.0.0.1:5173") + "/queue");
  await page.getByText("Reconnect Song", { exact: true }).waitFor();
  await page.evaluate(() => window.testStream.onopen?.({}));
  // The delivery completes while the browser is disconnected: no job event is sent.
  confirmed = true;
  await page.evaluate(() => {
    window.testStream.onerror?.({});
    window.testStream.onopen?.({});
  });
  await page.getByText("Archivo confirmado en Navidrome", { exact: false }).waitFor({ timeout: 5000 });
  assert.deepEqual(errors, []);
  console.log("PASS: queue recovers Navidrome confirmation missed while disconnected");
} finally {
  await browser.close();
}
