# Functional verification — 2026-09-11

The local saved-audio and Navidrome delivery flow passed. This is not a full production sign-off:
live song search encountered upstream errors, external downloaders were simulated in the integration
check, and the deployed containers/shared remote volume were not accessible for validation.

## Checks and evidence

| Area | Result |
| --- | --- |
| Backend | 105 pytest tests pass, including real ffmpeg metadata checks across WAV/MP3/FLAC/M4A/Opus, API auth/ranges, migrations and scan recovery. Ruff/Black clean. |
| Frontend | TypeScript and production build pass. Five routes, album error recovery, quality filtering, mobile layout and audio preview race checked in Chromium without page exceptions. |
| Local playback | Actual 3-second MP3 played from both Queue and Library through the HTTP app with a shared password; seeking and HTTP 206 verified. |
| Navidrome | Official v0.63.2 Linux binary in an isolated temporary directory; archive SHA256 matched release metadata. Real Subsonic authentication, scans and search used. |
| Delivery | POST `/api/downloads` ran the real queue/worker/subprocess path with a fixture CLI generating audio with wrong tags. The app repaired tags, recorded the file, and Navidrome indexed its exact relative path with the expected artist/title/album on attempt 1. |
| Recovery | Stopped the temporary Navidrome, enqueued another track: download completed, local playback worked, retry/error persisted, and deleting the pending job returned 409. Restarted Navidrome and the app: delivery became confirmed on attempt 4. |
| Live catalog | MusicBrainz artist and album searches returned results. Song searches returned upstream HTTP 503 and a timeout. Song search cannot be considered reliably working in this environment. |
| Dependencies | npm audit found no vulnerabilities; Python dependency consistency check passed. |

## Bugs reproduced and corrected during verification

- The browser reconnected its SSE transport without fetching events missed while disconnected.
  A finished Navidrome scan could remain shown as pending indefinitely. On connection, the frontend
  now fetches persisted jobs and merges them with live updates. The browser regression
  `tests/browser/sse_reconnect.mjs` failed before the fix and passed afterward.
- A metadata timeout produced an empty `Metadata source error:` message. Search now returns an
  actionable timeout message with HTTP 504, or a catalog availability message with HTTP 502 for
  other upstream failures. Two API regression cases cover these errors.

## Limits

- No production deployment or container image build was performed; Docker socket access is unavailable.
  The actual Navidrome mount, remote filesystem propagation and production permissions remain unchecked.
- The integration downloader was a synthetic-audio fixture, not real yt-dlp/spotDL traffic. Source
  selection and the correctness of audio fetched from YouTube/Spotify still need a live download check.
- Paid adapters remain unfinished integrations requiring provider-specific configuration; no paid
  account or live Telegram/Matrix bot was exercised.
- A successful synthetic-audio pipeline proves file handling and delivery, not catalog availability
  or whether an external source resolves the intended recording.

All integration data and services were temporary and separate from the user's music library.
