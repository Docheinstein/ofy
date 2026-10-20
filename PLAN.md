GOAL: Build "Ofy", a self-hosted, Spotify-style web app for browsing music via MusicBrainz,
downloading songs/albums offline from YouTube Music, tagging them fully with MusicBrainz metadata,
and fetching lyrics from LRCLIB.

STACK (do not deviate without asking):
- Backend: Python 3.12+, FastAPI (async), uv for deps, SQLite via SQLModel, httpx, ytmusicapi,
  yt-dlp (as a library, not subprocess), ffmpeg, mutagen, rapidfuzz. pytest for tests.
- Frontend: React + TypeScript + Vite + Tailwind + shadcn/ui + TanStack Query. Dark Spotify-like theme.
- Desktop shell: pywebview (native OS webview window; GTK/WebKit on Linux, optional Qt backend).
  Docker is NOT a requirement and is not used.
- Repo layout: backend/, frontend/, README.md.

FUNCTIONAL REQUIREMENTS

1. Metadata (MusicBrainz WS/2 JSON):
   - Search artists, release-groups (albums), recordings (songs).
   - Artist page: discography grouped by primary type (Album, Single/EP, Compilation, Live),
     related artists from artist relationships.
   - Album page: pick a canonical release per release-group (Official > digital/CD > earliest),
     allow switching edition; show tracklist with disc/track numbers and durations.
   - When a release is selected for download, fetch it with
     inc=recordings+artist-credits+labels+isrcs+genres+release-groups+media so all tag data
     is available in one request.
   - Cover art from Cover Art Archive (front image, prefer 1200px thumbnail).
   - Artist images: MusicBrainz has none, so use Wikidata/Wikimedia Commons (P18 of the artist's
     Wikidata item); fall back to one of the artist's album covers.
   - Strict global rate limit of 1 req/s, descriptive User-Agent, SQLite response cache with TTL.

2. Matching (YouTube Music via ytmusicapi):
   - Strategy A (preferred): find the official YT Music album (filter="albums"), score by
     album title/artist/year/track count, then map tracks by position + title + duration (±5s).
   - Strategy B (fallback per track): filter="songs", prefer Art Tracks over videos,
     penalize live/remix/cover/sped up/karaoke unless present in the MB title.
   - Every match stores a 0–1 confidence score; below a configurable threshold the track is
     "needs_review" and the UI lets the user choose among top-5 candidates. Manual choices persist.

3. Downloading:
   - Download a single track or a whole album. Persistent job queue (survives restart),
     configurable concurrency (default 2), retry with backoff.
   - yt-dlp bestaudio → ffmpeg. Output format configurable: mp3 (DEFAULT, 320 kbps CBR or V0,
     configurable), m4a (no re-encode when source is AAC), opus (no re-encode).
   - Save under a configurable library root using a configurable path template, default
     "{albumartist}/{album}/{artist} - {title}.{ext}", sanitizing names
     (illegal chars, trailing dots/spaces, max length) and handling multi-disc releases.
   - Write to a temp file, tag, then atomically move into the library.
   - Live progress pushed to the UI via WebSocket (stages: matching, downloading, converting,
     tagging, lyrics, done).

4. Tagging (MusicBrainz → file tags, via mutagen):
   - Implement a single format-agnostic tag model (dataclass) built from MusicBrainz data, plus
     writers for ID3v2.4 (mp3), MP4 atoms (m4a) and Vorbis comments (opus). Follow MusicBrainz
     Picard's tag mapping (https://picard-docs.musicbrainz.org/en/appendices/tag_mapping.html)
     so Jellyfin/Navidrome/Plex/Picard read them correctly.
   - Required fields: title, artist (full artist credit string), artists (multi-value),
     album, albumartist, artist sort / albumartist sort, track number/total, disc number/total,
     date (release date), originaldate (release-group first release date), genre (top MB genres),
     label, catalog number, barcode, ISRC, media format, release type, release status,
     release country, compilation flag, script/language when present, length.
   - MusicBrainz IDs: recording id (ID3: UFID http://musicbrainz.org), track id, release id,
     release-group id, artist id(s), album artist id(s), release track id; stored as
     TXXX:"MusicBrainz Album Id" etc. for ID3 and the equivalent keys for MP4/Vorbis.
   - Embedded front cover art (APIC type 3 / covr / METADATA_BLOCK_PICTURE).
   - Do NOT save a separate cover.jpg in the album folder (cover is embedded only).
   - Do NOT save the artist photo in the music folder either; it lives in the app's image cache.
   - Store the YouTube video id in a custom tag (e.g. TXXX:YOUTUBE_VIDEO_ID) for traceability.
   - Retagging: a "Refresh tags" action rewrites tags of already-downloaded files from fresh
     MusicBrainz data without re-downloading audio.

5. Lyrics (LRCLIB, https://lrclib.net/docs):
   - After tagging, call GET https://lrclib.net/api/get with artist_name, track_name,
     album_name and duration (seconds, from MB). On 404, fall back to /api/search and accept
     the best result whose duration is within ±2s and whose title/artist fuzzy-match above
     threshold. Send a descriptive User-Agent; throttle requests politely.
   - If syncedLyrics exists → save "<same basename>.lrc" next to the audio file
     (add [ar:], [al:], [ti:], [length:] headers).
     Else if plainLyrics exists → save "<same basename>.txt" next to the audio file.
     If instrumental → save nothing, record status "instrumental".
   - Also embed plain lyrics in the file (ID3 USLT / MP4 ©lyr / Vorbis LYRICS); configurable.
   - Lyrics are a best-effort step: a lyrics failure must never fail the track download.
   - Per-track lyrics status: none | synced | plain | instrumental | not_found, with a
     "Fetch lyrics again" action and a bulk "Fetch missing lyrics" action for an album/library.
   - Settings toggles: fetch lyrics (on), prefer synced (on), embed in tags (on).

6. Library state:
   - Per-track status: none | queued | downloading | done | failed | needs_review,
     plus lyrics status as above.
   - Album status derived: none | partial | complete — shown on album cards and headers.
   - Library scanner reconciles DB with disk by reading MBID tags (on startup + "Rescan" button),
     detecting audio and sidecar lyrics files removed or added outside the app.

7. Playback (bonus, keep simple):
   - GET /api/stream/{recording_mbid}: serve local file with HTTP range support if downloaded,
     otherwise match, extract via yt-dlp and proxy the audio stream through the backend.
   - Bottom player bar with play/pause/seek/volume using an HTML5 <audio> element.
   - Optional: lyrics panel that highlights the current line when an .lrc is available.

8. UI: left sidebar (Search, Library, Downloads, Settings), main content, bottom player bar.
   Track rows show download status icons (download / queued / progress ring / green check /
   warning+retry / needs-review) and a small lyrics indicator (synced / plain / none).
   A track detail drawer shows the written tags, match source + score, and lyrics.
   Settings page edits library path, output format + bitrate, path template, concurrency,
   match threshold, lyrics options, optional cookies.txt path.

WORK PLAN — execute in this order, committing after each phase:
  0 skeleton + settings
  1 MusicBrainz browsing
  2 matcher (+ CLI: `python -m ofy.match "<artist>" "<album>"` printing matches and scores)
  3 download pipeline (mp3 default)
  4 tagging (tag model + 3 writers + cover art + retag action)
  5 lyrics (LRCLIB client + sidecar files + embedding + statuses)
  6 library state + scanner
  7 playback
  8 polish
  9 desktop app (pywebview launcher, replaces Docker packaging)

DEFINITION OF DONE (verify each yourself before declaring completion):
- `uv run ofy-desktop` starts the backend and opens the UI in a native desktop window
  (pywebview); closing the window shuts the backend down. `uv run python -m ofy` still runs
  the plain web server with the UI at http://localhost:8080.
- Searching "Radiohead" → artist page → "OK Computer" shows 12 tracks with cover art.
- The matcher CLI returns the official YT Music album for: Radiohead/OK Computer,
  Daft Punk/Discovery, Adele/25, Nirvana/Nevermind, with ≥ 95% tracks above threshold.
- "Download album" on OK Computer produces a correctly named folder of MP3s (no cover.jpg);
  a verification script reads every file with mutagen and asserts: ID3v2.4, title/artist/album/
  albumartist/track n/total/disc/date/originaldate/genre/label/ISRC present, all MusicBrainz IDs
  present and equal to the source MBIDs, embedded front cover present.
- The same album downloaded as m4a and as opus passes the equivalent tag assertions.
- Each track has a sibling .lrc (or .txt when only plain lyrics exist) with the same basename;
  plain lyrics are embedded in the tags; the UI shows the lyrics indicator per track.
- An instrumental track (e.g. Radiohead "Fitter Happier" is spoken — use a known instrumental such
  as Daft Punk "Voyager" if LRCLIB marks it instrumental) gets no lyrics file and status
  "instrumental"; a lyrics API failure (simulate by pointing to an invalid host) still yields
  a successfully downloaded and tagged track.
- Deleting one audio file and clicking Rescan turns that track back to "not downloaded" and the
  album to "partial"; deleting only a .lrc updates the lyrics indicator.
- "Refresh tags" rewrites tags without re-downloading (file mtime of audio stream unchanged
  except for tag write; no network call to YouTube).
- A non-downloaded track plays in the player bar via the proxy endpoint.
- pytest passes: unit tests for match scoring, path templating/sanitizing, status aggregation,
  MB rate limiter, MB→tag-model mapping (from recorded JSON fixtures), each tag writer
  (round-trip write/read on tiny generated audio files), LRCLIB result selection and .lrc
  formatting. Network tests are marked and skippable.
- README documents setup, configuration, tag mapping table, lyrics behaviour, and the
  yt-dlp update procedure.

CONSTRAINTS
- Never exceed MusicBrainz rate limits; throttle LRCLIB; never hammer YouTube
  (respect concurrency, add jitter).
- Keep matching, tag mapping and lyrics selection logic pure and unit-testable (no I/O).
- Ask before adding major dependencies not listed above.