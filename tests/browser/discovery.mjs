// Isolated UI acceptance. Run against Vite or the built app; every API is intercepted.
import assert from "node:assert/strict";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  headless: true, args: ["--no-sandbox"],
});
const base = process.env.CHECK_BASE_URL || "http://127.0.0.1:5173";
const contexts = [await browser.newContext(), await browser.newContext()];
const pages = [], errors = [];
const status = {configured: true, stale: false, refreshing: false, error: null, updated_at: "2026-09-11T12:00:00Z", generation: "one"};
const local = {id: "local", track: {title: "Local Song", artist: "Family Artist", album: "Album", ext_ids: {}, catalog_id: "local"}, catalog_id: "local", availability: "available", saved: false, favorite: false, dismissed: false, job_done: false};
const suggestion = {id: "new", track: {title: "New Song", artist: "New Artist", ext_ids: {mbid: "0c1199cf-969c-4e92-84b7-a1c3ee6a88c4"}}, reason: "Relacionado con Family Artist", availability: "missing", saved: false, favorite: false, dismissed: false, job_done: false};
let queueCalls = 0, externalDown = false, disabled = false;
async function changed() {
  for (const page of pages) {
    if (!page.url().startsWith(base)) continue;
    await page.evaluate(() => window.testStream?.onmessage?.({data: JSON.stringify({type: "collection"})})).catch(error => {
      if (!error.message.includes("Execution context was destroyed")) throw error;
    });
  }
}
for (const context of contexts) {
  await context.addInitScript(() => {
    window.EventSource = class {constructor() {window.testStream = this;} close() {}};
  });
  await context.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    let data = [];
    if (path === "/api/catalog/tracks") data = {items: [local], total: 1, offset: 0, status};
    if (path === "/api/discovery") {
      if (url.searchParams.get("kind") === "external") {
        if (externalDown) return route.fulfill({status: 502, json: {detail: "External catalog unavailable"}});
        data = {enabled: true, items: [suggestion], artists: [], refreshing: false};
      } else data = {enabled: !disabled, items: [local], status};
    }
    if (path === "/api/health") data = {app: "ok", db_ok: true, queue: {workers: 2, active: 0, running: 0, queued: 0}};
    if (path === "/api/settings") data = {metadata: "musicbrainz", providers: []};
    if (path === "/api/search") data = {kind: "song", tracks: [], albums: [], artists: []};
    if (path === "/api/family/tracks") {
      if (request.method() === "PUT") {
        const body = request.postDataJSON();
        const card = body.track.title === local.track.title ? local : suggestion;
        for (const flag of ["saved", "favorite", "dismissed"]) if (flag in body) card[flag] = body[flag];
        data = card;
        await route.fulfill({json: data});
        await changed();
        return;
      }
      const flag = url.searchParams.get("mode") || "saved";
      data = {items: [local, suggestion].filter(c => c[flag]), has_more: false};
    }
    if (path === "/api/family/tracks/new/download") {
      queueCalls++;
      suggestion.availability = "downloading";
      suggestion.job_id = "job";
      await route.fulfill({json: {job_id: "job"}});
      await changed();
      return;
    }
    return route.fulfill({json: data});
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  pages.push(page);
}
try {
  const [a, b] = pages;
  await a.goto(base);
  await a.getByRole("heading", {name: "Descubrir en familia"}).waitFor();
  const newCard = a.getByRole("article", {name: "New Artist — New Song", exact: true}).first();
  await newCard.getByRole("button", {name: "Guardar para después", exact: true}).click();
  assert.equal(queueCalls, 0, "Saving a suggestion must never start a download");
  await b.goto(base + "/saved");
  const saved = b.getByRole("article", {name: "New Artist — New Song", exact: true});
  await saved.getByRole("button", {name: "♡ Favorita", exact: true}).click();
  await newCard.getByRole("button", {name: "♥ Favorita", exact: true}).waitFor();
  await saved.getByRole("button", {name: "Añadir a la biblioteca", exact: true}).click();
  await newCard.getByText("Descargando", {exact: true}).waitFor();
  assert.equal(queueCalls, 1);
  suggestion.favorite = false; // This change occurred while the first browser was disconnected.
  await a.evaluate(() => window.testStream.onopen?.({}));
  await newCard.getByRole("button", {name: "♡ Favorita", exact: true}).waitFor();
  externalDown = true;
  await changed();
  await a.getByText("External catalog unavailable", {exact: false}).waitFor();
  await a.getByRole("article", {name: "Family Artist — Local Song", exact: true}).waitFor();
  await a.setViewportSize({width: 390, height: 844});
  assert(await a.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  disabled = true;
  await a.goto(base);
  await a.waitForURL("**/search");
  assert.deepEqual(errors, []);
  console.log("PASS: discovery, shared selections, explicit download, reconnect, external outage, mobile layout and homepage disable");
} finally {
  await browser.close();
}
