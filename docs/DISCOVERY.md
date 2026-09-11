# Discovery and shared family collection

First product-plan delivery, implemented September 2026. The app now separates finding music,
keeping a shared shortlist, downloading it, and confirming its availability in Navidrome.

## Using the web app

- **Descubrir** (`/`): daily local rediscovery, external suggestions based on up to five selected
  MusicBrainz artists, and saved tracks. Artist choices include disambiguation where available.
  Suggestions explain their seed artist. Six are shown initially, with an option to show more.
- **Buscar** (`/search`): local matches appear independently of Spotify/MusicBrainz search.
  An external service failure does not hide the local matches.
- **Biblioteca** (`/library`): the complete indexed Navidrome catalog, including files imported
  outside mymusicdl. Search and pagination run on the server; refresh requests a new snapshot.
  The previous download history remains available at `/library/downloads`.
- **Pendientes** (`/saved`): shared saved, favorite and dismissed tracks. Saving never downloads.
  Choose a source and explicitly add a track to the existing queue when ready.

Preferences belong to the household, persist in SQLite and survive job deletion and restart.
SSE updates open clients; reconnect, window focus and periodic refresh recover missed updates.
Saving and favoriting are independent changes, so concurrent actions do not overwrite each other.

**Escuchar archivo descargado** plays the saved file. Catalog playback streams the original
Navidrome file through the backend, including byte ranges for seeking. The browser receives a
short-lived resource-scoped ticket, never Navidrome credentials. External previews, where
available, are labeled as a reference and do not verify the downloaded file. Browser codec support
still applies: an unsupported original format is not automatically transcoded.

## Catalog consistency and identity

`Catalog` reads all `search3` pages until an empty page, including servers that cap page sizes.
It checks scan state before and after fetching, then commits the full snapshot atomically. Failed,
repeating or interrupted pagination preserves the previous snapshot and marks it stale. The UI
shows unknown availability when verification is stale, rather than declaring those songs absent.
The external-search badge also distinguishes a failed lookup from a confirmed non-match.

Indexing runs at startup, every six hours, and on manual refresh. Failed refreshes retry after a
minute. A confirmed download is indexed immediately. Generation tokens detect catalog changes
during pagination; the client restarts at the first page if its snapshot is no longer current.
The index is scoped to the configured server and Navidrome account.

MusicBrainz recording IDs identify family selections when available. Each Navidrome file retains
its own catalog ID, even when multiple files share a recording ID. Playback of a concrete catalog
entry resolves that file, not another edition with the same recording. Download tagging preserves
valid MusicBrainz recording and artist IDs so confirmed downloads can join existing selections.
Tracks lacking strong identifiers use a metadata-derived key; ambiguous historical matches are
not silently treated as the same recording. Full version management and collision-free versioned
download naming remain later roadmap work.

## External suggestions and configuration

ListenBrainz receives selected artist IDs and metadata lookup IDs. The app does not send family
listening history. Suggestions are cached in SQLite for 24 hours, deduplicated and capped at 20,
with at most two per artist. Dismissed tracks are excluded. Requests are serialized, rate limited,
and retried for transient failures. A failed refresh preserves the last suggestions and exposes a
status message; retry is delayed five minutes. Local discovery remains usable independently.

Both options default to `true` and are loaded on process startup:

```dotenv
DISCOVERY_ENABLED=true
DISCOVERY_EXTERNAL_ENABLED=true
```

Set `DISCOVERY_ENABLED=false` to return the homepage to search. Catalog and saved-track pages
remain accessible. Set `DISCOVERY_EXTERNAL_ENABLED=false` to disable ListenBrainz suggestions.
The existing Compose `env_file` passes these settings through; restart/recreate the app to apply.

New tables are `catalog_tracks`, `catalog_state`, `family_tracks`, `family_artists` and
`discovery_cache`. Startup creates them without replacing existing jobs or library items.
Additive catalog-state columns use the existing idempotent upgrade mechanism. Back up the SQLite
data directory before upgrading as usual. Clearing job history does not clear family selections.

## Verification and release scope

Backend acceptance tests cover a 601-song catalog with capped pages, interrupted snapshots,
refresh during pagination, old-schema upgrade, persistent family selections, concurrent preference
changes, distinct recordings and exact file playback, seed changes, external outages, limits,
queue deduplication, protected audio tickets, ranges and upstream error handling:

```bash
pytest -q
ruff check backend tests
black --check backend tests
cd frontend
npm run build
```

With the app or Vite running, an isolated browser acceptance test exercises two independent
browser contexts, saved tracks without downloads, explicit queue actions, SSE recovery, external
outage with local results intact, mobile layout and the homepage switch:

```bash
CHECK_BASE_URL=http://127.0.0.1:8080 node tests/browser/discovery.mjs
```

Install Playwright separately, or set `PLAYWRIGHT_MODULE` to its absolute `index.mjs` path and
`CHROMIUM_PATH` to an installed Chromium binary. API responses in this test are mocked.

Additional local integration checks used an isolated **Navidrome 0.63.2** instance and the actual
app lifespan, worker, database, scanner and browser. They verified:

- A Navidrome-only imported MP3 appears in the catalog and plays/seeks through the protected proxy.
- A saved/favorite track passes through the queue, tagging, real Navidrome scan and catalog
  confirmation with its recording ID; preferences and playback survive deletion of its job.
- Two independent browser sessions see shared preference changes.
- Real ListenBrainz artist recommendations reach the homepage.

The downloader executable in that integration test generated a short synthetic MP3. These checks
verify the delivery pipeline but **do not establish current YouTube/Spotify download reliability**.
Before considering the production rollout verified, download an authorized real-source track in
the deployed environment, audition its actual file, and confirm it appears in the production
Navidrome catalog. Local tests do not validate the production shared volume or edge proxy.

Collections/export, full recording-version management and AudioMuse integration are later
deliveries and are not included in this release.
