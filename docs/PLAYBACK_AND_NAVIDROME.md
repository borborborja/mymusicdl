# Saved-file playback and Navidrome delivery

The **Descargas** and **Biblioteca** pages offer **Escuchar archivo descargado**. This plays the
file saved in the music volume, including when Navidrome is unavailable. It does not resolve a new
YouTube source. The player supports pause, seeking and opening the original file. Browser format
support varies; opening the original file remains available if the browser cannot decode it.

The existing optional shared password is checked before issuing a playback URL. The URL is valid
for one hour and grants access only to the requested job or library item. Streaming supports HTTP
byte ranges and only serves recorded, nonempty audio files inside `MUSIC_LIBRARY_PATH`. Reopen the
player if its URL expires. Library playback still works after the associated job history is removed.

## Delivery after a download

1. Resolve the expected audio output inside the shared music volume.
2. Write the selected title, artist, album and available album-artist/ISRC tags using ffmpeg stream
   copy. Keep existing artwork and additional metadata. The replacement is prepared in the same
   directory, retains file permissions and replaces the original only after success. Audio is not
   re-encoded. A tagging failure is a visible download error, not a false success.
3. Persist the local library entry and mark the download done, with Navidrome delivery pending.
4. A background reconciler batches pending downloads. It waits for an existing scan to finish,
   requests a fresh scan and waits for that scan before looking up each file.
5. Confirmation requires the exact relative file path in Navidrome's search results, not simply
   another copy with the same title/artist. Save its Navidrome ID and invalidate cached library
   badges after confirmation.
6. Failed scans and files not yet visible are retried with persisted backoff. Subsequent attempts
   request a full scan. Pending work survives application restarts. Old unconfirmed downloads also
   have their tags prepared before scanning.

The queue shows `pending`, `syncing`, `confirmed`, `error` or `unconfigured` as user-facing messages,
plus the error explanation and next retry time where relevant. **Reintentar sincronización** resets
a failed delivery's retry budget without downloading the audio again. Pending delivery records are
kept when clearing finished job history. Delivery events do not generate repeated bot completion
notifications.

## Settings

Environment settings (also accepted through the existing `.env` loading):

| Variable | Default | Purpose |
| --- | --- | --- |
| `NAVIDROME_SCAN_TIMEOUT_S` | `180` | Maximum wait for an existing or newly requested scan. Increase for large libraries. |
| `NAVIDROME_SYNC_RETRY_S` | `30` | Initial retry delay, doubled after each attempt and capped at 300 seconds. |
| `NAVIDROME_SYNC_MAX_ATTEMPTS` | `5` | Automatic attempts before showing a persistent error and offering manual retry. |

The reconciler checks due work every five seconds and is also notified after downloads/manual
retries. The new delivery columns are added idempotently to existing SQLite databases by
`_ensure_columns`; no manual migration is required for these additive fields.

## If Navidrome still cannot find a file

Listen to the local file first to establish whether the downloaded audio is correct. Then inspect
the queue's delivery message:

- **Not configured:** set the existing `NAVIDROME_URL`, `NAVIDROME_USER` and `NAVIDROME_PASSWORD`.
- **Scan/connectivity failure:** verify connectivity and the account's permission to request scans.
- **File absent after scans:** check that both services mount the same music volume, that Navidrome
  can read the directories/files, and that `.ndignore` does not exclude them. Remote mounts can
  expose newly written files later than the writer sees them; retries accommodate that delay.
- **Local file missing:** check the mounted volume and recorded path. Re-scanning cannot recreate
  a missing audio file.

The app cannot repair a different/missing Navidrome mount or change another container's permissions.
It reports that delivery is unconfirmed instead of treating a successful downloader process as
proof that Navidrome received the file.

Navidrome organizes its library using embedded tags, not directory names:
[Navidrome tagging guidelines](https://www.navidrome.org/docs/usage/library/tagging/).
Scan status and scan requests use the Subsonic interface:
[startScan](https://opensubsonic.netlify.app/docs/endpoints/startscan/) and
[getScanStatus](https://opensubsonic.netlify.app/docs/endpoints/getscanstatus/).

## Verification

`tests/test_library_playback_sync.py` covers exact-byte playback, range/HEAD requests, access tickets,
path escapes, schema upgrades, scan ordering, timeouts, retries, restart recovery, exact file
confirmation, cache invalidation and metadata correction with real ffmpeg across WAV, MP3, FLAC,
M4A and Opus. Audio tests require ffmpeg; CI installs it explicitly.

Local Chromium verification exercised playback and seeking through the real HTTP server with a
real MP3, a configured shared password and a simulated Navidrome that exposed the file after the
second scan. This validates the application flow, not a particular deployed Navidrome instance.

A follow-up check used an isolated, real Navidrome instance with a shared temporary music folder:
HTTP enqueue, subprocess-produced test audio, metadata correction, scan, exact-path confirmation
and browser playback all passed. Delivery also recovered after stopping Navidrome and restarting
the application. The downloader executable in this test generated synthetic audio; it did not
download from YouTube or Spotify. See [functional verification](FUNCTIONAL-VERIFICATION-2026-09-11.md)
for the observed limits and remaining deployment checks.
