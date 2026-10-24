import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Disc, EllipsisVertical, ExternalLink, FolderInput, Loader2, MicVocal, Play, RefreshCw, Search, User, Volume2, X } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, coverUrl, isLocal, type ImportResult, type LibraryAlbum, type LibraryTrack } from "@/lib/api";
import { ArtistAvatar } from "@/components/ArtistAvatar";
import { Button } from "@/components/ui/button";
import { Cover } from "@/components/Cover";
import { Input } from "@/components/ui/input";
import { LyricsIndicator } from "@/components/StatusIcons";
import { Plays } from "@/components/Plays";
import { SyncToggle } from "@/components/SyncToggle";
import { TrackDrawer } from "@/components/TrackDrawer";
import { useCompact } from "@/lib/hooks";
import { usePlayer } from "@/lib/player";
import { useSyncSelection } from "@/lib/sync";
import { cn, formatDuration } from "@/lib/utils";

type SyncFilter = "all" | "synced" | "unsynced";

const SYNC_FILTERS: { value: SyncFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "synced", label: "Synced" },
  { value: "unsynced", label: "Not synced" },
];

/** Which artists and albums are unfolded; kept for the tab so going back from an album restores the tree.
 * While searching, nodes leading to a match start unfolded instead; folding one lasts until the search changes. */
function useExpanded(q: string) {
  const [open, setOpen] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(sessionStorage.getItem("library-open") ?? "[]") as string[]);
    } catch {
      return new Set();
    }
  });
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      try {
        sessionStorage.setItem("library-open", JSON.stringify([...next]));
      } catch {
        /* not persisted */
      }
      return next;
    });
  const [flipped, setFlipped] = useState<{ q: string; keys: Set<string> }>({ q, keys: new Set() });
  const flippedKeys = flipped.q === q ? flipped.keys : new Set<string>();
  const flip = (key: string) => {
    const next = new Set(flippedKeys);
    if (!next.delete(key)) next.add(key);
    setFlipped({ q, keys: next });
  };
  return {
    isOpen: (key: string, revealed: boolean) => (revealed ? !flippedKeys.has(key) : open.has(key)),
    toggle: (key: string, revealed: boolean) => (revealed ? flip(key) : toggle(key)),
  };
}

export function LibraryPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  // ?sync=synced|unsynced, kept in the URL so it survives going back from an album or artist
  const syncParam = params.get("sync");
  const filter: SyncFilter = syncParam === "synced" || syncParam === "unsynced" ? syncParam : "all";
  const setFilter = (f: SyncFilter) => {
    const next = new URLSearchParams(params);
    if (f === "all") next.delete("sync");
    else next.set("sync", f);
    setParams(next, { replace: true });
  };
  // ?q= narrows the tree to matching artists, albums and songs
  const q = params.get("q") ?? "";
  const needle = q.trim().toLowerCase();
  const setQuery = (v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set("q", v);
    else next.delete("q");
    setParams(next, { replace: true });
  };
  const sel = useSyncSelection();
  const expanded = useExpanded(needle);
  const { data, isLoading } = useQuery({ queryKey: ["library"], queryFn: () => api.get<LibraryAlbum[]>("/api/library/albums") });
  const rescan = useMutation({
    mutationFn: () => api.post<{ changed: number }>("/api/library/rescan"),
    onSuccess: () => qc.invalidateQueries(),
  });
  const lyrics = useMutation({ mutationFn: () => api.post<{ queued: number }>("/api/library/lyrics") });
  const importFiles = useMutation({
    mutationFn: () => api.post<ImportResult>("/api/library/import-files"),
    onSuccess: () => qc.invalidateQueries(),
  });
  // the song whose details (tags, match, lyrics) are open in the drawer
  const [open, setOpen] = useState<Opened | null>(null);

  // Synced is decided per song: picked on its own, or brought along by its album or artist.
  const isSynced = (a: LibraryAlbum, t: LibraryTrack) =>
    sel.has("track", t.track_id) || sel.has("album", a.release_id) || sel.has("artist", a.artist_id);
  const matches = (text: string) => text.toLowerCase().includes(needle);
  // The search first: a matching artist or album brings all its songs, otherwise only the matching songs remain.
  const searched: Shown[] = (data ?? []).flatMap((a): Shown[] => {
    if (!needle || matches(a.artist)) return [{ album: a, songs: a.tracks, reveal: "none" }];
    if (matches(a.title)) return [{ album: a, songs: a.tracks, reveal: "artist" }];
    const songs = a.tracks.filter((t) => matches(t.title));
    return songs.length ? [{ album: a, songs, reveal: "album" }] : [];
  });
  const counts: Record<SyncFilter, number> = { all: 0, synced: 0, unsynced: 0 };
  for (const { album: a, songs } of searched) {
    for (const t of songs) {
      counts.all++;
      counts[isSynced(a, t) ? "synced" : "unsynced"]++;
    }
  }
  // Then the sync filter: each album keeps only the songs matching it, so one album can show up under both.
  const albums: Shown[] = searched
    .map((s) => ({ ...s, songs: filter === "all" ? s.songs : s.songs.filter((t) => isSynced(s.album, t) === (filter === "synced")) }))
    .filter((s) => (filter === "all" && s.songs === s.album.tracks) || s.songs.length > 0);
  const groups = groupByArtist(albums);

  // Phone-sized windows show one level at a time instead of the tree: ?artist= (a group key), then ?album= (a release).
  const compact = useCompact();
  const drill = useDrill();
  if (compact && (drill.artist || drill.album)) {
    if (!data) return <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin" /></div>;
    // what the filters leave of it, or all of it when they leave nothing
    const everything = groupByArtist(data.map((a) => ({ album: a, songs: a.tracks, reveal: "none" as const })));
    const find = (list: Group[]) =>
      drill.album
        ? list.flatMap((g) => g.albums.map((s) => ({ g, s }))).find(({ s }) => s.album.release_id === drill.album)
        : list.map((g) => ({ g, s: null })).find(({ g }) => g.key === drill.artist);
    const found = find(groups) ?? find(everything);
    return (
      <div className="pb-6">
        {!found ? (
          <>
            <DrillBar title="Library" onBack={() => drill.up(null)} />
            <p className="px-4 text-muted-foreground">This isn't in the library any more.</p>
          </>
        ) : found.s ? (
          <AlbumView shown={found.s} group={found.g} filtered={filter !== "all" || !!needle} onBack={() => drill.up(found.g.key)} onOpen={setOpen} />
        ) : (
          <ArtistView group={found.g} filtered={filter !== "all" || !!needle} onBack={() => drill.up(null)} onAlbum={(id) => drill.to({ album: id })} />
        )}
        <TrackDrawer track={open?.track ?? null} releaseId={open?.releaseId ?? ""} onClose={() => setOpen(null)} />
      </div>
    );
  }

  return (
    <div className="p-6 max-md:px-3 max-md:pt-4">
      <div className="mb-6 flex flex-wrap items-center gap-4 max-md:mb-4 max-md:gap-2">
        <h1 className="text-3xl font-extrabold max-md:text-2xl">Your Library</h1>
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={() => lyrics.mutate()} disabled={lyrics.isPending} title="Fetch missing lyrics" className="max-md:w-8 max-md:px-0">
          {lyrics.isPending ? <Loader2 className="animate-spin" /> : <MicVocal />} <span className="max-md:hidden">Fetch missing lyrics</span>
        </Button>
        <Button variant="secondary" size="sm" onClick={() => importFiles.mutate()} disabled={importFiles.isPending} title="Tag songs put into album folders by hand" className="max-md:w-8 max-md:px-0">
          {importFiles.isPending ? <Loader2 className="animate-spin" /> : <FolderInput />} <span className="max-md:hidden">Tag added files</span>
        </Button>
        <Button variant="secondary" size="sm" onClick={() => rescan.mutate()} disabled={rescan.isPending} title="Rescan" className="max-md:w-8 max-md:px-0" data-testid="rescan">
          {rescan.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} <span className="max-md:hidden">Rescan</span>
        </Button>
      </div>
      {lyrics.data && <p className="mb-4 text-sm text-muted-foreground">Queued lyrics lookups for {lyrics.data.queued} tracks.</p>}
      {rescan.data && <p className="mb-4 text-sm text-muted-foreground">Rescan complete — {rescan.data.changed} changes.</p>}
      {importFiles.data && (
        <p className="mb-4 break-all text-sm text-muted-foreground">
          Tagged {importFiles.data.imported.length} added songs in {importFiles.data.albums} album folders.
          {importFiles.data.unmatched.length > 0 && ` ${importFiles.data.unmatched.length} didn't match a missing song of their album, so they stay as they are.`}
          {importFiles.data.failed.length > 0 && ` Couldn't tag: ${importFiles.data.failed.join(", ")}.`}
        </p>
      )}
      <div className="relative mb-4 max-w-xl">
        <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setQuery("")}
          placeholder="Filter artists, albums and songs"
          className="h-10 rounded-full border-none bg-elevated pl-11 pr-10"
          data-testid="library-search"
        />
        {q && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear filter"
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter songs by sync state">
        {SYNC_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            aria-pressed={filter === value}
            data-testid={`sync-filter-${value}`}
            className={cn(
              "rounded-full px-3 py-1 text-sm font-semibold transition-colors",
              filter === value ? "bg-foreground text-background" : "bg-elevated text-foreground hover:bg-elevated/70",
            )}
          >
            {label} {data && <span className="font-normal opacity-60">{counts[value]}</span>}
          </button>
        ))}
      </div>
      {isLoading && <Loader2 className="animate-spin" />}
      {data && data.length === 0 && <p className="text-muted-foreground">Nothing here yet. Search for an album and download it.</p>}
      {data && data.length > 0 && searched.length === 0 && (
        <p className="text-muted-foreground">Nothing in the library matches “{q.trim()}”.</p>
      )}
      {searched.length > 0 && groups.length === 0 && (
        <p className="text-muted-foreground">
          {filter === "synced"
            ? `No ${needle ? "matching " : ""}songs are selected for sync yet.`
            : `Every ${needle ? "matching" : "downloaded"} song is selected for sync.`}
        </p>
      )}
      {compact ? (
        <div className="-mx-1 flex flex-col" data-testid="library-list">
          {groups.map((g) => (
            <RootRows key={g.key} group={g} searching={!!needle} drill={drill} onOpen={setOpen} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col" data-testid="library-tree">
          {groups.map((g) => (
            <ArtistNode key={g.key} group={g} filtered={filter !== "all" || !!needle} expanded={expanded} onOpen={setOpen} />
          ))}
        </div>
      )}
      <TrackDrawer track={open?.track ?? null} releaseId={open?.releaseId ?? ""} onClose={() => setOpen(null)} />
    </div>
  );
}

/** An album as shown under the current filters: only its matching songs. */
interface Shown {
  album: LibraryAlbum;
  songs: LibraryTrack[];
  /** How far the tree unfolds by itself to show what the search matched. */
  reveal: "none" | "artist" | "album";
}

interface Group {
  key: string;
  artist: string;
  artistId: string | null;
  albums: Shown[];
}

type Expanded = ReturnType<typeof useExpanded>;

interface Opened {
  track: LibraryTrack;
  releaseId: string;
}

type OnOpen = (o: Opened) => void;

/** Albums arrive sorted by artist → year → title; bucket them by artist, keeping that order. */
function groupByArtist(albums: Shown[]): Group[] {
  const groups = new Map<string, Group>();
  for (const s of albums) {
    const a = s.album;
    const key = a.artist_id ?? `name:${a.artist.toLowerCase()}`;
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { key, artist: a.artist, artistId: a.artist_id, albums: [] }));
    g.albums.push(s);
  }
  return [...groups.values()];
}

const plural = (n: number, word: string) => `${n} ${n === 1 ? word : `${word}s`}`;

function Caret({ open }: { open: boolean }) {
  return <ChevronRight className={cn("h-5 w-5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />;
}

function Avatar({ group: g, className }: { group: Group; className: string }) {
  return g.artistId ? (
    <ArtistAvatar id={g.artistId} fallbackRg={g.albums[0].album.release_group_id} className={`${className} shrink-0`} />
  ) : (
    <div className={`${className} flex shrink-0 items-center justify-center rounded-full bg-elevated text-muted-foreground shadow-lg`}>
      <User className="h-1/3 w-1/3" />
    </div>
  );
}

/** An artist; unfolding it lists their albums right below. */
function ArtistNode({ group: g, filtered, expanded, onOpen }: { group: Group; filtered: boolean; expanded: Expanded; onOpen: OnOpen }) {
  const revealed = g.albums.some((s) => s.reveal !== "none");
  const open = expanded.isOpen(g.key, revealed);
  const songs = g.albums.reduce((n, s) => n + s.songs.length, 0);
  return (
    <section data-testid="library-artist">
      <div className="group flex items-center gap-2 rounded-md pr-3 transition-colors hover:bg-elevated">
        <button
          type="button"
          onClick={() => expanded.toggle(g.key, revealed)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left"
          data-testid="library-artist-row"
        >
          <Caret open={open} />
          <Avatar group={g} className="h-12 w-12" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-semibold">{g.artist}</div>
            <div className="text-sm text-muted-foreground">
              {plural(g.albums.length, "album")} • {plural(songs, "song")}
            </div>
          </div>
        </button>
        {g.artistId && (
          <>
            <SyncToggle target={{ kind: "artist", id: g.artistId, title: g.artist, subtitle: "Artist" }} hideWhenOff />
            {!isLocal(g.artistId) && (
              <Link
                to={`/artist/${g.artistId}`}
                aria-label={`Open ${g.artist}`}
                title="Open artist page"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
              >
                <ExternalLink className="h-4 w-4" />
              </Link>
            )}
          </>
        )}
      </div>
      {open && (
        <div className="ml-6 border-l pl-2">
          {g.albums.map((s) => (
            <AlbumNode key={s.album.release_id} shown={s} filtered={filtered} expanded={expanded} onOpen={onOpen} />
          ))}
        </div>
      )}
    </section>
  );
}

/** An album under its artist; unfolding it lists its downloaded songs (only those matching the filter). */
function AlbumNode({ shown: { album: a, songs, reveal }, filtered, expanded, onOpen }: {
  shown: Shown; filtered: boolean; expanded: Expanded; onOpen: OnOpen;
}) {
  const key = `album:${a.release_id}`;
  const open = expanded.isOpen(key, reveal === "album");
  const detail = filtered
    ? plural(songs.length, "song")
    : `${a.library.done}/${a.library.total} tracks`;
  return (
    <div data-testid="library-album" data-release-id={a.release_id}>
      <div className="group flex items-center gap-2 rounded-md pr-3 transition-colors hover:bg-elevated">
        <button
          type="button"
          onClick={() => expanded.toggle(key, reveal === "album")}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left"
          data-testid="library-album-row"
        >
          <Caret open={open} />
          <Cover src={coverUrl("release", a.release_id, 250, a.release_group_id)} alt={a.title} className="h-10 w-10 shrink-0" rounded="rounded" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{a.title}</div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              {[a.year, detail].filter(Boolean).join(" • ")}
              <Plays n={a.plays} />
            </div>
          </div>
        </button>
        <SyncToggle target={{ kind: "album", id: a.release_id, title: a.title, subtitle: a.artist }} artistId={a.artist_id} hideWhenOff />
        <Link
          to={`/album/${a.release_group_id}`}
          aria-label={`Open ${a.title}`}
          title="Open album page"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <ExternalLink className="h-4 w-4" />
        </Link>
      </div>
      {open && (
        <div className="ml-8 border-l pl-2">
          {songs.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">No songs downloaded yet.</p>}
          <SongList album={a} songs={songs} onOpen={onOpen} />
        </div>
      )}
    </div>
  );
}

function SongList({ album: a, songs, onOpen, compact, withAlbum }: {
  album: LibraryAlbum; songs: LibraryTrack[]; onOpen: OnOpen; compact?: boolean; withAlbum?: boolean;
}) {
  const player = usePlayer();
  const multiDisc = songs.some((t) => t.disc !== songs[0].disc);
  const playFrom = (i: number) =>
    player.playList(
      songs.map((t) => ({
        recording_id: t.recording_id,
        track_id: t.track_id,
        release_id: a.release_id,
        title: t.title,
        artist: t.artist,
        length_ms: t.length_ms,
        cover: coverUrl("release", a.release_id, 250, a.release_group_id),
      })),
      i,
    );
  let lastDisc = 0;
  const Row = compact ? CompactSongRow : SongRow;
  return (
    <>
      {songs.map((t, i) => {
        const header = multiDisc && t.disc !== lastDisc && !withAlbum;
        lastDisc = t.disc;
        return (
          <div key={t.track_id}>
            {header && (
              <div className="flex items-center gap-2 px-3 pb-1 pt-3 text-xs font-bold text-muted-foreground">
                <Disc className="h-3.5 w-3.5" /> Disc {t.disc}
              </div>
            )}
            <Row album={a} t={t} withAlbum={withAlbum} onPlay={() => playFrom(i)} onOpen={() => onOpen({ track: t, releaseId: a.release_id })} />
          </div>
        );
      })}
    </>
  );
}

interface SongRowProps {
  album: LibraryAlbum;
  t: LibraryTrack;
  /** Say which album it's from (search results outside their album). */
  withAlbum?: boolean;
  onPlay: () => void;
  onOpen: () => void;
}

/** A downloaded song: click for its details (tags, match, lyrics), double-click to play. */
function SongRow({ album: a, t, onPlay, onOpen }: SongRowProps) {
  const { current, playing } = usePlayer();
  const isCurrent = current?.track_id === t.track_id;
  return (
    <div
      className={cn(
        "group grid cursor-pointer items-center gap-3 rounded-md px-3 py-1.5 hover:bg-elevated",
        t.plays !== undefined ? "grid-cols-[2rem_1fr_4rem_1.5rem_3.5rem_2rem]" : "grid-cols-[2rem_1fr_1.5rem_3.5rem_2rem]",
      )}
      onClick={onOpen}
      onDoubleClick={onPlay}
      data-testid="library-song"
      data-track-id={t.track_id}
    >
      <div className="flex justify-end text-sm tabular-nums text-muted-foreground">
        <span className={cn("group-hover:hidden", isCurrent && "text-primary")}>
          {isCurrent && playing ? <Volume2 className="h-4 w-4" /> : t.position}
        </span>
        <button
          className="hidden text-foreground group-hover:block"
          onClick={(e) => { e.stopPropagation(); onPlay(); }}
          aria-label={`Play ${t.title}`}
        >
          <Play className="h-4 w-4 fill-current" />
        </button>
      </div>
      <div className="min-w-0">
        <div className={cn("truncate text-[15px]", isCurrent && "text-primary")}>{t.title}</div>
        {t.artist !== a.artist && <div className="truncate text-sm text-muted-foreground">{t.artist}</div>}
      </div>
      {t.plays !== undefined && <div className="flex justify-end"><Plays n={t.plays} /></div>}
      <div className="flex justify-center"><LyricsIndicator status={t.lyrics_status} /></div>
      <div className="text-right text-sm tabular-nums text-muted-foreground">{formatDuration(t.length_ms)}</div>
      <SyncToggle
        target={{ kind: "track", id: t.track_id, title: t.title, subtitle: `${t.artist} — ${a.title}` }}
        artistId={a.artist_id}
        releaseId={a.release_id}
        hideWhenOff
      />
    </div>
  );
}

/** A song on a touch screen: tap to play, the menu button for its details. */
function CompactSongRow({ album: a, t, withAlbum, onPlay, onOpen }: SongRowProps) {
  const { current, playing } = usePlayer();
  const isCurrent = current?.track_id === t.track_id;
  const sub = [t.artist !== a.artist || withAlbum ? t.artist : null, withAlbum ? a.title : null, formatDuration(t.length_ms)].filter(Boolean).join(" • ");
  return (
    <div
      role="button"
      tabIndex={0}
      className="flex cursor-pointer items-center gap-3 rounded-md py-1.5 pl-3 transition-colors active:bg-elevated"
      onClick={onPlay}
      onKeyDown={(e) => e.key === "Enter" && onPlay()}
      data-testid="library-song"
      data-track-id={t.track_id}
    >
      {withAlbum ? (
        <Cover src={coverUrl("release", a.release_id, 250, a.release_group_id)} alt="" className="h-11 w-11 shrink-0" rounded="rounded" />
      ) : (
        <div className={cn("w-5 shrink-0 text-right text-sm tabular-nums text-muted-foreground", isCurrent && "text-primary")}>
          {isCurrent && playing ? <Volume2 className="ml-auto h-4 w-4" /> : t.position}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className={cn("truncate text-[15px]", isCurrent && "text-primary")}>{t.title}</div>
        <div className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
          {t.lyrics_status !== "none" && <LyricsIndicator status={t.lyrics_status} />}
          <span className="truncate">{sub}</span>
          <Plays n={t.plays} />
        </div>
      </div>
      <SyncToggle
        target={{ kind: "track", id: t.track_id, title: t.title, subtitle: `${t.artist} — ${a.title}` }}
        artistId={a.artist_id}
        releaseId={a.release_id}
        className="h-10 w-10"
      />
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onOpen(); }}
        aria-label={`Details of ${t.title}`}
        className="-ml-1 flex h-10 w-9 shrink-0 items-center justify-center text-muted-foreground active:text-foreground"
        data-testid="song-details"
      >
        <EllipsisVertical className="h-5 w-5" />
      </button>
    </div>
  );
}

type Drill = ReturnType<typeof useDrill>;

/** The library level shown on phone-sized windows, in the URL so the phone's back gesture goes up a level. */
function useDrill() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const go = (to: { artist?: string; album?: string }, replace: boolean) => {
    const next = new URLSearchParams(params);
    next.delete("artist");
    next.delete("album");
    if (to.artist) next.set("artist", to.artist);
    if (to.album) next.set("album", to.album);
    setParams(next, { replace, state: replace ? location.state : { drilled: true } });
  };
  return {
    artist: params.get("artist"),
    album: params.get("album"),
    to: (to: { artist?: string; album?: string }) => go(to, false),
    /** Back where this level was opened from, or (opened from a link) to the level above. */
    up: (artist: string | null) =>
      (location.state as { drilled?: boolean } | null)?.drilled ? navigate(-1) : go(artist ? { artist } : {}, true),
  };
}

/** The top of a drilled-down level: back, and the name once the header has scrolled away. */
function DrillBar({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <div className="sticky top-0 z-10 flex h-12 items-center gap-1 bg-surface/90 px-1 backdrop-blur" data-testid="drill-bar">
      <button type="button" onClick={onBack} aria-label="Back" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full active:bg-elevated">
        <ChevronLeft className="h-6 w-6" />
      </button>
      <span className="truncate font-bold">{title}</span>
    </div>
  );
}

function OpenPage({ to, label }: { to: string; label: string }) {
  return (
    <Button variant="outline" size="sm" asChild>
      <Link to={to}><ExternalLink /> {label}</Link>
    </Button>
  );
}

/** On phone-sized windows: an artist row of the library, or what the search found in their albums. */
function RootRows({ group: g, searching, drill, onOpen }: { group: Group; searching: boolean; drill: Drill; onOpen: OnOpen }) {
  const songs = g.albums.reduce((n, s) => n + s.songs.length, 0);
  // not searching, or the artist matched: the artist; otherwise the albums and songs that matched
  if (!searching || g.albums.some((s) => s.reveal === "none")) {
    return (
      <ListRow
        art={<Avatar group={g} className="h-14 w-14" />}
        title={g.artist}
        detail={`${plural(g.albums.length, "album")} • ${plural(songs, "song")}`}
        sync={g.artistId ? <SyncToggle target={{ kind: "artist", id: g.artistId, title: g.artist, subtitle: "Artist" }} onlyWhenOn /> : null}
        onClick={() => drill.to({ artist: g.key })}
        testId="library-artist-row"
      />
    );
  }
  return (
    <>
      {g.albums.map((s) =>
        s.reveal === "artist" ? (
          <AlbumRow key={s.album.release_id} shown={s} filtered withArtist onClick={() => drill.to({ album: s.album.release_id })} />
        ) : (
          <SongList key={s.album.release_id} album={s.album} songs={s.songs} onOpen={onOpen} compact withAlbum />
        ),
      )}
    </>
  );
}

function ListRow({ art, title, detail, sync, onClick, testId }: {
  art: React.ReactNode; title: string; detail: React.ReactNode; sync: React.ReactNode; onClick: () => void; testId: string;
}) {
  return (
    <div className="flex items-center rounded-md transition-colors active:bg-elevated">
      <button type="button" onClick={onClick} className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left" data-testid={testId}>
        {art}
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">{title}</div>
          <div className="truncate text-sm text-muted-foreground">{detail}</div>
        </div>
      </button>
      {sync}
      <ChevronRight className="mr-2 h-5 w-5 shrink-0 text-muted-foreground" />
    </div>
  );
}

function AlbumRow({ shown: { album: a, songs }, filtered, withArtist, onClick }: { shown: Shown; filtered: boolean; withArtist?: boolean; onClick: () => void }) {
  const detail = filtered ? plural(songs.length, "song") : `${a.library.done}/${a.library.total} tracks`;
  return (
    <ListRow
      art={<Cover src={coverUrl("release", a.release_id, 250, a.release_group_id)} alt="" className="h-14 w-14 shrink-0" rounded="rounded" />}
      title={a.title}
      detail={<>{[withArtist ? a.artist : null, a.year, detail].filter(Boolean).join(" • ")} <Plays n={a.plays} className="ml-1 align-middle" /></>}
      sync={<SyncToggle target={{ kind: "album", id: a.release_id, title: a.title, subtitle: a.artist }} artistId={a.artist_id} onlyWhenOn />}
      onClick={onClick}
      testId="library-album-row"
    />
  );
}

/** On phone-sized windows: an artist's albums, in place of the library. */
function ArtistView({ group: g, filtered, onBack, onAlbum }: { group: Group; filtered: boolean; onBack: () => void; onAlbum: (releaseId: string) => void }) {
  const songs = g.albums.reduce((n, s) => n + s.songs.length, 0);
  return (
    <div data-testid="library-artist-view">
      <DrillBar title={g.artist} onBack={onBack} />
      <header className="flex flex-col items-center gap-3 px-4 pb-4 text-center">
        <Avatar group={g} className="h-36 w-36" />
        <div className="min-w-0 max-w-full">
          <h1 className="line-clamp-2 break-words text-3xl font-black tracking-tight">{g.artist}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{plural(g.albums.length, "album")} • {plural(songs, "song")}</p>
        </div>
        {g.artistId && (
          <div className="flex flex-wrap justify-center gap-2">
            <SyncToggle variant="button" className="h-8 px-3 text-xs" target={{ kind: "artist", id: g.artistId, title: g.artist, subtitle: "Artist" }} />
            {!isLocal(g.artistId) && <OpenPage to={`/artist/${g.artistId}`} label="Artist page" />}
          </div>
        )}
      </header>
      <div className="flex flex-col px-1">
        {g.albums.map((s) => (
          <AlbumRow key={s.album.release_id} shown={s} filtered={filtered} onClick={() => onAlbum(s.album.release_id)} />
        ))}
      </div>
    </div>
  );
}

/** On phone-sized windows: an album's downloaded songs, in place of the library. */
function AlbumView({ shown: { album: a, songs }, group: g, filtered, onBack, onOpen }: {
  shown: Shown; group: Group; filtered: boolean; onBack: () => void; onOpen: OnOpen;
}) {
  const player = usePlayer();
  const play = () =>
    songs.length &&
    player.playList(
      songs.map((t) => ({
        recording_id: t.recording_id,
        track_id: t.track_id,
        release_id: a.release_id,
        title: t.title,
        artist: t.artist,
        length_ms: t.length_ms,
        cover: coverUrl("release", a.release_id, 250, a.release_group_id),
      })),
    );
  return (
    <div data-testid="library-album-view" data-release-id={a.release_id}>
      <DrillBar title={a.title} onBack={onBack} />
      <header className="flex flex-col items-center gap-3 px-4 pb-2 text-center">
        <Cover src={coverUrl("release", a.release_id, 500, a.release_group_id)} alt={a.title} className="w-44" />
        <div className="min-w-0 max-w-full">
          <h1 className="line-clamp-2 break-words text-2xl font-black tracking-tight">{a.title}</h1>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">{g.artist}</span>
            {a.year && ` • ${a.year}`} • {a.library.done}/{a.library.total} tracks
            <Plays n={a.plays} className="ml-2 align-middle" />
          </p>
        </div>
      </header>
      <div className="flex items-center gap-2 px-4 pb-3">
        <SyncToggle variant="button" className="h-8 px-3 text-xs" target={{ kind: "album", id: a.release_id, title: a.title, subtitle: a.artist }} artistId={a.artist_id} />
        <OpenPage to={`/album/${a.release_group_id}?release=${a.release_id}`} label="Album page" />
        <div className="flex-1" />
        <button
          type="button"
          onClick={play}
          disabled={!songs.length}
          className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-black shadow-lg active:scale-95 disabled:opacity-50"
          aria-label="Play album"
        >
          <Play className="ml-0.5 h-5 w-5 fill-current" />
        </button>
      </div>
      {filtered && songs.length < a.tracks.length && (
        <p className="px-4 pb-2 text-xs text-muted-foreground">{plural(songs.length, "song")} of {a.tracks.length} match the filters.</p>
      )}
      <div className="px-1">
        {songs.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">No songs downloaded yet.</p>}
        <SongList album={a} songs={songs} onOpen={onOpen} compact />
      </div>
    </div>
  );
}
