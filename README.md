# Ofy

A self-hosted, Spotify-style web app for **browsing music via MusicBrainz**, **downloading** songs and
albums from **YouTube Music**, **tagging** them completely with MusicBrainz metadata (Picard-compatible, so
Jellyfin / Navidrome / Plex / Picard read them correctly), and fetching **lyrics** from **LRCLIB**.

```
Search ─▶ Artist ─▶ Album (pick edition) ─▶ Download
                                         │
            match on YT Music (album → per-song fallback, confidence 0–1)
                                         │
     yt-dlp bestaudio ─▶ ffmpeg (mp3 / m4a / opus) ─▶ tag (ID3v2.4 / MP4 / Vorbis) + cover
                                         │
                  LRCLIB lyrics (.lrc sidecar when well-timed + embedded) ─▶ atomic move into library
```

* **Backend**: Python 3.12+, FastAPI, SQLModel/SQLite, httpx, ytmusicapi, yt-dlp (as a library), ffmpeg,
  mutagen, rapidfuzz — managed with `uv`.
* **Frontend**: React + TypeScript + Vite + Tailwind + shadcn/ui-style components + TanStack Query.

---

## Quick start

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 18+, GNU make, ffmpeg (and ideally `deno` or
Node ≥ 20 on `PATH` for yt-dlp, see [Updating yt-dlp](#updating-yt-dlp)).

```bash
make build          # install backend + frontend dependencies and build the UI
make run            # open the desktop app (builds first if anything is missing or out of date)
```

| Command | What it does |
|---|---|
| `make` / `make build` | `uv sync` (backend) + `npm ci` (frontend) + `npm run build`, each only when out of date |
| `make clean` | Deletes `backend/.venv`, `frontend/node_modules` and `frontend/dist` |
| `make test` | Runs the backend unit tests |
| `make run` | Desktop app (native window). Extra args go to `ofy-desktop` via `ARGS`, e.g. `make run ARGS=--debug` |
| `make web [PORT=8080]` | Web server only; UI at http://localhost:8080 |
| `make help` | Lists the targets |

`make run` and `make web` rebuild automatically when the virtualenv or `node_modules` is missing or
older than its lockfile, or when any UI source is newer than `frontend/dist`. To add Ofy to
your app menu: `cd backend && uv run ofy-desktop --install-shortcut`.

### Desktop app

`ofy-desktop` starts the backend in a background thread (listening on `127.0.0.1` only) and shows
the UI in a native window via [pywebview](https://pywebview.flowrl.com/). Closing the window stops the
backend. If a backend for the same data directory is already running (another window, or the web server
below) the window attaches to it instead of starting a second job queue on the same database.

* Music goes to `~/Music/Ofy` by default (change it in Settings).
* App state (SQLite DB, MusicBrainz/YT caches, cover cache, temp files) lives in
  `~/.local/share/ofy` (`$XDG_DATA_HOME/ofy`).
* Upgrading from the app's former name (Offliner): `~/.local/share/offliner` is moved to `~/.local/share/ofy`
  automatically on first start (only when the new folder doesn't exist yet and the old app isn't running).
* Set `OFY_CONTACT=you@example.com` so the MusicBrainz/LRCLIB User-Agent carries a contact, as
  MusicBrainz asks.

**Webview backends.** On Linux the window uses GTK + WebKitGTK. PyGObject has no pip wheels, so the
launcher reuses the distro's bindings (only `gi`/`cairo` are linked into the virtualenv):

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1 gstreamer1.0-libav gstreamer1.0-plugins-good   # Debian/Ubuntu
```

`gstreamer1.0-libav` provides AAC/MP3 decoding for the player. The launcher sets
`WEBKIT_DISABLE_DMABUF_RENDERER=1` unless it's already set (WebKitGTK's DMA-BUF renderer crashes on
NVIDIA under Wayland). Without GTK, use the Qt backend instead:
`uv sync --extra qt && uv run ofy-desktop --gui qt`. macOS (WebKit) and Windows (Edge WebView2)
need nothing extra.

`uv run ofy-desktop --selftest [--play /api/stream/<recording-mbid>]` opens the window, checks
that the UI renders and which audio codecs the webview supports, optionally plays a stream, prints a
JSON report and exits; use it to diagnose a machine.

### Web server mode

The same app also runs as a plain web server (e.g. on a home server, used from any browser):
`make web`, or directly `cd backend && uv run python -m ofy` (UI on http://localhost:8080).

### Android (Termux)

On a phone Ofy runs as a web app: the server in [Termux](https://termux.dev), the UI in the browser.

```bash
termux-setup-storage    # once: lets the library live in shared storage (Music/Ofy)
./termux.sh setup       # installs packages, the backend venv and the UI build
./termux.sh             # starts the server and opens http://localhost:8080
```

The first setup is slow: Termux has no prebuilt wheels, so pydantic-core (Rust), rapidfuzz and a
few C extensions are compiled on the phone. If the UI won't build there, run `make` on a
computer and copy `frontend/dist` over. The server listens on localhost only (set `OFY_HOST=0.0.0.0`
to reach it over Wi-Fi) and holds a Termux wake lock while running so downloads aren't suspended.
The desktop window (`ofy-desktop`) isn't available on Android.

## Development

For live reload while editing, run the backend and the Vite dev server in two terminals: Python under
`backend/src` and TypeScript under `frontend/src` reload on save.

```bash
cd backend && uv run uvicorn ofy.main:app --port 8080 --reload --reload-dir src
cd frontend && npm run dev          # http://localhost:5173, proxies /api to :8080
```

### Tests

```bash
cd backend
uv run pytest                 # unit tests (offline)
uv run pytest -m network      # live tests against MusicBrainz + YouTube Music
```

Unit tests cover: match scoring and album/track mapping, path templating & sanitizing, status
aggregation, the MusicBrainz rate limiter, MusicBrainz → tag-model mapping (recorded JSON fixtures in
`tests/fixtures`), every tag writer (round-trip on tiny ffmpeg-generated mp3/m4a/opus files), LRCLIB
result selection, `.lrc` formatting and sidecar handling, the job queue (retry, backoff, persistence,
concurrency) and "Refresh tags" (asserts no YouTube access and an unchanged audio stream).

### Useful commands

```bash
# Matcher CLI: prints the chosen YT Music album and per-track matches + scores
uv run python -m ofy.match "Radiohead" "OK Computer"
uv run python -m ofy.match "Nirvana" "Nevermind" --threshold 0.8 -v

# Verify a downloaded album folder against MusicBrainz (tags, MBIDs, cover, ID3v2.4, sidecars)
uv run python scripts/verify_album.py "music/Radiohead/1997 - OK Computer" <release-mbid> --format mp3

# Headless browser smoke test of the UI (needs chromium)
uv run python scripts/ui_check.py --base http://localhost:8080
```

---

## Configuration

Environment variables (bootstrap, read at start):

| Variable | Default | Meaning |
|---|---|---|
| `OFY_DATA_DIR` | `~/.local/share/ofy` | SQLite DB, caches, temp files |
| `OFY_LIBRARY_DIR` | `~/Music/Ofy` | Default library root |
| `OFY_PORT` / `OFY_HOST` | `8080` / `0.0.0.0` (desktop: `127.0.0.1`) | HTTP listen address; the desktop app falls back to a free port if 8080 is taken |
| `OFY_CONTACT` | empty | Contact (email/URL) appended to the User-Agent |
| `OFY_STATIC_DIR` | `<repo>/frontend/dist` | Built frontend to serve |
| `OFY_MUSICBRAINZ_URL` | `https://musicbrainz.org/ws/2` | MusicBrainz WS/2 base (e.g. a mirror) |
| `OFY_SCAN_ON_STARTUP` | `1` | Reconcile DB with disk at startup |

Settings page (persisted in the DB, editable at runtime):

| Setting | Default | Notes |
|---|---|---|
| Library path | `OFY_LIBRARY_DIR` | Root folder for downloads |
| Path template | `{albumartist}/{album}/{artist} - {title}.{ext}` | See below |
| Output format | `mp3` | `mp3` (re-encode), `m4a` (copy when the source is AAC), `opus` (copy) |
| MP3 quality | `320` | `320` kbps CBR or `v0` VBR |
| Concurrent downloads | `2` | Size of the download worker pool |
| Max retries | `3` | Exponential backoff with jitter between attempts |
| Match threshold | `0.7` | Below → track becomes **needs review** |
| Fetch lyrics / Prefer synced / Embed in tags | on / on / on | LRCLIB behaviour |
| LRCLIB URL | `https://lrclib.net` | Point elsewhere (e.g. self-hosted LRCLIB) |
| cookies.txt path | empty | Optional Netscape cookies file for yt-dlp (age-restricted content) |

**Path template fields**: `albumartist artist album title year date originalyear disc disctotal track
tracktotal ext media releasetype catalognumber label albumartistsort artistsort`. Python format specs
work (`{track:02}`). `{year}` is the release group's original year (stable across reissues). Every path
component is sanitized: characters illegal on Windows/macOS/Linux (`<>:"/\|?*` and control characters)
become `_`, leading/trailing dots and spaces are removed, Windows reserved names (`CON`, `NUL`, …) get a
suffix, and each component is limited to 180 bytes (the extension is preserved). Values can never create
extra directories (`AC/DC` → `AC_DC`). The default produces e.g. `Pink Floyd/Meddle/Pink Floyd - Echoes.mp3`
(and `Pink Floyd - Echoes.lrc` next to it); `{artist}` is the track's artist credit. If two tracks of a
release render to the same name (the same song twice, or on several discs) the later one gets a
` (disc-track)` suffix instead of overwriting. Add `{disc}-{track:02} - ` to the template if you prefer
numbered files.

## How it works

### MusicBrainz

* WS/2 JSON with a **strict global limit of 1 request/second** (one shared limiter, serialized across
  all coroutines), a descriptive User-Agent, retries on 503, and an SQLite response cache with TTLs
  (searches 1 day, entities 3–7 days).
* Artist pages group release groups into **Album, Single/EP, Compilation, Live** (and Other), plus
  related artists from artist–artist relationships.
* The canonical edition of a release group is chosen as **Official > Digital Media/CD > earliest date**
  (precise dates beat year-only dates; ties prefer worldwide/major-market releases). Any edition can be
  selected in the album page's edition picker.
* For tagging, the selected release is fetched once with
  `inc=recordings+artist-credits+labels+isrcs+genres+release-groups+media`.
* Artist photos come from Wikidata/Wikimedia Commons (MusicBrainz has none): the artist's Wikidata item
  (MusicBrainz's `wikidata` link, or a lookup by MusicBrainz artist ID, property P434) and its image
  (P18), as a Commons thumbnail. Without a photo, the artist page uses the cover of the artist's newest
  album. Lookups are cached (30 days, 7 for "no photo"), throttled to 1 request/s, and on HTTP 429 all
  Wikimedia requests pause for the server's `Retry-After`.
* Cover art comes from the Cover Art Archive (`front-1200`, falling back to the original image, then to
  the release group's cover) and is cached on disk.

### Matching (YouTube Music)

* **Strategy A (album)**: search `filter="albums"`, score candidates on title / artist / year / track
  count, fetch the best ones and map tracks one-to-one by **position + title + duration (±5 s)**. Album
  entries that point at music videos are replaced by their **Art Track** from the album's audio
  playlist.
* **Strategy B (per song)**: `filter="songs"`; prefers Art Tracks over videos and penalizes
  live / remix / cover / sped up / slowed / karaoke / instrumental / acoustic… unless the MusicBrainz
  title contains the same word.
* MusicBrainz tracks that combine several songs (e.g. `Something in the Way / Endless, Nameless` with a
  hidden track) are matched to the consecutive YT tracks and **concatenated** at download time.
* Every match stores a **0–1 confidence**, its source (`album`, `song`, `manual`) and the top 5
  candidates. Below the threshold the track is **needs review**: the track drawer lists candidates
  (with links to listen on YT Music) and "Use this" persists a manual choice that is never overridden
  by automatic re-matching.
* All YouTube Music calls go through one throttled client (≈1 request/s with jitter) and are cached.

### Downloading

* Persistent job queue in SQLite (jobs survive restarts; interrupted jobs resume), configurable
  concurrency, retries with exponential backoff + jitter, and a random pause before each download.
* yt-dlp (`bestaudio`, preferring the codec that can be kept) → ffmpeg → tag → lyrics → **atomic move**
  (temp file in the destination directory, `fsync`, `rename`). The front cover is only embedded in
  the files (no `cover.jpg` is written). The artist's photo (Wikidata/Commons) is fetched into the
  app's image cache (`<data dir>/covers/`), never into the music folder.
* Live progress (`matching → downloading → converting → tagging → lyrics → done`) is pushed over the
  WebSocket at `/api/ws`.

### Downloading from a YouTube link

* The **Downloads** page takes a pasted YouTube link: a video (`watch?v=`, `youtu.be/`, `/shorts/`;
  a watch link opened inside a playlist still means just that video) downloads that one song, a
  playlist (`playlist?list=`, or a YouTube Music album) downloads every song in it.
* YouTube is only the audio source, as for everything else. Each video's title, artists, album and
  length (from YouTube Music; "Artist - Title" uploads are read both ways) are searched on
  MusicBrainz. The recording is scored on title, artist and length (a radio edit or live take is
  a different recording; a music video's length is trusted less than official audio's). Recordings
  on the artist's own studio albums and on many releases rank first, ahead of a compilation's own
  copy of a hit. The song is filed under a release already in the library, else the album YouTube
  names, else the canonical official release, never a various-artists compilation if the artist's
  own release has it.
* A confident match downloads the pasted video as that MusicBrainz track, tagged and named like
  any other download. A song already in the library is not downloaded again. Without a confident
  match, the video waits for you to choose a recording among the closest ones, or search MusicBrainz.

### Library state

* Track status: `none | queued | downloading | done | failed | needs_review`; lyrics status:
  `none | synced | plain | instrumental | not_found`.
* Album status is derived: `none | partial | complete` (shown on cards and album headers).
* The **library scanner** runs at startup and from the Library page's **Rescan** button. It walks the
  library, reads MusicBrainz ids from tags for unknown files, and reconciles: deleted audio → track back
  to `none` (album becomes `partial`); moved files are followed; files added outside the app (with MBID
  tags) are adopted; `.lrc` sidecars added or removed update the lyrics status.
* **Refresh tags** (album page) re-fetches the release from MusicBrainz (bypassing the cache) and
  rewrites tags in place — no YouTube access, the audio stream is untouched. If the new metadata
  renders to a different path, the file and its sidecars are moved.

### Playback

`GET /api/stream/{recording_mbid}` serves the local file with HTTP Range support when downloaded;
otherwise it matches the recording (album context when `?release=` is given), resolves the audio URL with
yt-dlp and proxies it through the backend (Range requests forwarded). The bottom player bar has
play/pause/seek/volume/next/previous, and the lyrics panel highlights the current line of the `.lrc`.

### Sync to a remote peer

Mark artists, albums or songs with the cloud button (Library, artist and album pages, track rows) to
keep them on another computer. Selecting an artist or album covers everything below it, including
tracks downloaded later; children of a selected parent show as included. The **Sync** page holds the
destination and runs the transfer:

* **Destination**: host (name/IP), user, password, SSH port, folder and an optional SSH key. Leave the
  host empty to sync to a local folder instead (a mounted drive, a USB stick…). Log in with an SSH key
  (`ssh-copy-id user@host`) or a password. The password is stored in plain text in the database, and
  `GET /api/settings` only returns a mask for it. `ssh` gets the password through an `SSH_ASKPASS`
  helper (`<data dir>/sync/askpass`, which reads it from the environment), so this needs OpenSSH 8.4+
  on this computer. New host keys are accepted on first connect. **Test connection** creates the
  folder and checks that the remote has `rsync`.
* **Transfer**: `rsync` (needed on both ends) copies the selected audio files and their `.lrc`
  sidecars, keeping the library's folder layout. Ofy mirrors the selection as a tree of symlinks in
  `<data dir>/sync/stage` and rsyncs that with `--copy-links`, so only changed files are sent. With
  **Mirror the selection** on (default) files in the destination that aren't selected are deleted —
  use a folder only Ofy writes to. A sync that would empty the destination is refused.
* **Preview changes** is a dry run listing what would be copied and deleted. Progress is pushed over
  the WebSocket; a running sync can be cancelled.

## Lyrics behaviour

1. After tagging, the real length of the downloaded file is read, and
   `GET {LRCLIB}/api/get?artist_name=…&track_name=…&album_name=…&duration=…` is called with it (in
   seconds; MusicBrainz's length only if the file's can't be read).
2. On 404 (or an empty record), `GET /api/search` and accept the best result whose **duration is within
   ±2 s** and whose title **and** artist fuzzy-match ≥ 0.8 (synced results preferred). The search also
   runs when the `/api/get` record's synced lyrics aren't trusted (see 3), looking for an entry that is.
3. Synced lyrics are **trusted** only if all of these hold, otherwise they're treated as plain lyrics:
   * the file's real length is within **±1 s** of LRCLIB's duration, and of MusicBrainz's length when known;
   * the audio comes from a single YouTube video (not several joined);
   * at least 5 timed lines, in order, the last one before the end of the file.
4. Result handling:
   * trusted `syncedLyrics` (and *prefer synced* on) → `<same basename>.lrc` next to the audio, with
     `[ar:]`, `[al:]`, `[ti:]` and `[length:mm:ss]` (the file's real length) headers → status **synced**;
   * else plain lyrics → **no sidecar**, only embedded in the tags (players such as Poweramp read them
     there) → status **plain** (or **none** with *embed in tags* off, as nothing is saved);
   * `instrumental: true` → nothing saved, status **instrumental**;
   * nothing acceptable → status **not_found**.

   With *embed in tags* on, the plain text is always embedded (ID3 `USLT`, MP4 `©lyr`, Vorbis `LYRICS`);
   for synced-only results the timestamps are stripped. `.txt` sidecars written by older versions are
   removed whenever a track's lyrics are saved again.
5. Lyrics are **best effort**: network errors, timeouts or HTTP errors are logged, the track still
   completes as `done` (status stays `none`), and existing sidecars and embedded lyrics are never
   removed because of an error.
6. Requests carry the Ofy User-Agent and are throttled (≥ 0.5 s apart).
7. "Fetch lyrics again" (track drawer) and "Fetch missing lyrics" (album page, Library page) retry
   tracks whose status is `none` or `not_found`.

## Tag mapping

Follows [Picard's tag mapping](https://picard-docs.musicbrainz.org/en/appendices/tag_mapping.html)
(verified against Picard's `formats/id3.py`, `mp4.py`, `vorbis.py`). MP4 freeform atoms are
`----:com.apple.iTunes:<name>`.

| Field (Picard name) | ID3v2.4 (mp3) | MP4 (m4a) | Vorbis (opus) |
|---|---|---|---|
| title | `TIT2` | `©nam` | `TITLE` |
| artist (full credit) | `TPE1` | `©ART` | `ARTIST` |
| artists (multi) | `TXXX:ARTISTS` | `ARTISTS` | `ARTISTS` |
| album | `TALB` | `©alb` | `ALBUM` |
| albumartist | `TPE2` | `aART` | `ALBUMARTIST` |
| albumartists (multi) | `TXXX:ALBUMARTISTS` | `ALBUMARTISTS` | `ALBUMARTISTS` |
| artistsort | `TSOP` | `soar` | `ARTISTSORT` |
| albumartistsort | `TSO2` | `soaa` | `ALBUMARTISTSORT` |
| tracknumber / totaltracks | `TRCK` (`n/t`) | `trkn` | `TRACKNUMBER` / `TRACKTOTAL` |
| discnumber / totaldiscs | `TPOS` (`n/t`) | `disk` | `DISCNUMBER` / `DISCTOTAL` |
| discsubtitle | `TSST` | `DISCSUBTITLE` | `DISCSUBTITLE` |
| date (release date) | `TDRC` | `©day` | `DATE` |
| originaldate (release group first release) | `TDOR` | `originaldate` | `ORIGINALDATE` |
| originalyear | `TXXX:originalyear` | `originalyear` | `ORIGINALYEAR` |
| genre (top MB genres, multi) | `TCON` | `©gen` | `GENRE` |
| label | `TPUB` | `LABEL` | `LABEL` |
| catalognumber | `TXXX:CATALOGNUMBER` | `CATALOGNUMBER` | `CATALOGNUMBER` |
| barcode | `TXXX:BARCODE` | `BARCODE` | `BARCODE` |
| isrc | `TSRC` | `ISRC` | `ISRC` |
| asin | `TXXX:ASIN` | `ASIN` | `ASIN` |
| media | `TMED` | `MEDIA` | `MEDIA` |
| releasetype | `TXXX:MusicBrainz Album Type` | `MusicBrainz Album Type` | `RELEASETYPE` |
| releasestatus | `TXXX:MusicBrainz Album Status` | `MusicBrainz Album Status` | `RELEASESTATUS` |
| releasecountry | `TXXX:MusicBrainz Album Release Country` | `MusicBrainz Album Release Country` | `RELEASECOUNTRY` |
| compilation (album artist is Various Artists) | `TCMP` = `1` | `cpil` | `COMPILATION` = `1` |
| script | `TXXX:SCRIPT` | `SCRIPT` | `SCRIPT` |
| language | `TLAN` | `LANGUAGE` | `LANGUAGE` |
| length (ms) | `TLEN` | `LENGTH` | `LENGTH` |
| lyrics (plain) | `USLT` | `©lyr` | `LYRICS` |
| front cover | `APIC` (type 3) | `covr` | `METADATA_BLOCK_PICTURE` (type 3) |
| musicbrainz_recordingid | `UFID:http://musicbrainz.org` | `MusicBrainz Track Id` | `MUSICBRAINZ_TRACKID` |
| musicbrainz_trackid (release track id) | `TXXX:MusicBrainz Release Track Id` | `MusicBrainz Release Track Id` | `MUSICBRAINZ_RELEASETRACKID` |
| musicbrainz_albumid (release id) | `TXXX:MusicBrainz Album Id` | `MusicBrainz Album Id` | `MUSICBRAINZ_ALBUMID` |
| musicbrainz_releasegroupid | `TXXX:MusicBrainz Release Group Id` | `MusicBrainz Release Group Id` | `MUSICBRAINZ_RELEASEGROUPID` |
| musicbrainz_artistid (multi) | `TXXX:MusicBrainz Artist Id` | `MusicBrainz Artist Id` | `MUSICBRAINZ_ARTISTID` |
| musicbrainz_albumartistid (multi) | `TXXX:MusicBrainz Album Artist Id` | `MusicBrainz Album Artist Id` | `MUSICBRAINZ_ALBUMARTISTID` |
| YouTube video id (traceability) | `TXXX:YOUTUBE_VIDEO_ID` | `YOUTUBE_VIDEO_ID` | `YOUTUBE_VIDEO_ID` |

Notes: as in Picard, Vorbis `MUSICBRAINZ_TRACKID` holds the *recording* id and the release-track id is
`MUSICBRAINZ_RELEASETRACKID`. Release type/status are lower-case (`album`, `official`). Genres are the
top 5 genres merged from recording, release and release group by vote count, written as separate values;
for players that show them as one genre (e.g. Poweramp reading ID3v2.4), Settings → Tags can join them
into one value with a separator or keep only the top genre. MP3 files are saved as
ID3v2.4 without an ID3v1 tag. Composite (concatenated) matches store all video ids joined with `+`.

## Updating yt-dlp

YouTube changes frequently; when downloads start failing (403s, "Sign in to confirm", format errors),
update yt-dlp first:

```bash
cd backend
uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs && uv sync
# then restart Ofy (close and reopen the window, or restart `python -m ofy`)
```

`yt-dlp[default]` pulls in `yt-dlp-ejs` (the JS challenge solver scripts). yt-dlp also needs a JavaScript
runtime on `PATH` to solve YouTube's player challenges: install [Deno](https://deno.com)
(`curl -fsSL https://deno.land/install.sh | sh`) or Node ≥ 20. Without one, extraction still works for now
but some formats may be missing and you may see more HTTP 403s. If YouTube requires sign-in for some
tracks, export cookies from a browser to a `cookies.txt` (Netscape format) and set its path in Settings.

## API overview

| Method & path | Purpose |
|---|---|
| `GET /api/search?q=&type=all\|artist\|album\|track` | MusicBrainz search |
| `GET /api/artist/{id}` · `GET /api/release-group/{id}` · `GET /api/release/{id}` | Browse (+ library state) |
| `GET /api/cover/{release\|release-group}/{id}?size=250\|500\|1200` | Cached Cover Art Archive images |
| `GET /api/artist-image/{id}?size=…&fallback_rg=…&wikidata=…` | Artist photo (Wikidata/Commons, album-cover fallback) |
| `POST /api/release/{id}/download` · `POST /api/release/{id}/tracks/{tid}/download` · `POST /api/recording/{id}/download` | Queue downloads |
| `GET /api/track/{tid}` · `POST /api/track/{tid}/retry` · `POST /api/track/{tid}/match` · `POST /api/release/{id}/tracks/{tid}/candidates` | Track detail, retry, manual match, candidates |
| `POST /api/track/{tid}/lyrics` · `POST /api/release/{id}/lyrics` · `POST /api/library/lyrics` | Lyrics refetch / fill missing |
| `POST /api/release/{id}/retag` | Refresh tags |
| `GET /api/library/albums` · `POST /api/library/rescan` | Library |
| `GET /api/downloads` · `POST /api/downloads/clear` · `POST /api/downloads/retry-failed` | Queue view |
| `POST /api/youtube/import` · `GET /api/youtube/imports` · `POST /api/youtube/imports/{id}/match\|retry` · `DELETE /api/youtube/imports/{id}` · `POST /api/youtube/imports/clear` | Downloads from YouTube links |
| `GET /api/stream/{recording_id}` · `GET /api/lyrics/{recording_id}` | Playback |
| `GET/PUT /api/sync/selection` · `GET /api/sync/summary` · `POST /api/sync/test` · `POST /api/sync/run` · `GET /api/sync/status` · `POST /api/sync/cancel` | Sync selection and transfers |
| `GET/PUT /api/settings` · `WS /api/ws` | Settings, live events |
