import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, Download, ExternalLink, Loader2, RotateCw, Search, Trash2, TvMinimalPlay, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, coverUrl, type MBCandidate, type SearchResult, type YTImport, type YTImportStarted } from "@/lib/api";
import { useLiveTrack } from "@/lib/live";
import { Button } from "@/components/ui/button";
import { Cover } from "@/components/Cover";
import { Input } from "@/components/ui/input";
import { TrackStatusButton } from "@/components/StatusIcons";
import { cn, formatDuration } from "@/lib/utils";

const watchUrl = (videoId: string) => `https://www.youtube.com/watch?v=${videoId}`;

/** Paste a YouTube video or playlist link: each video is matched to a MusicBrainz song and
 * downloaded as that song, tagged from MusicBrainz like everything else. */
export function YouTubeImports() {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const { data } = useQuery({
    queryKey: ["yt-imports"],
    queryFn: () => api.get<YTImport[]>("/api/youtube/imports"),
    // quicker while videos are being looked up, so they move on without waiting
    refetchInterval: (q) => (q.state.data?.some((i) => i.status === "resolving") ? 1500 : 5000),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["yt-imports"] });
  const start = useMutation({
    mutationFn: (u: string) => api.post<YTImportStarted>("/api/youtube/import", { url: u }),
    onSuccess: () => {
      setUrl("");
      refresh();
    },
  });
  const clear = useMutation({ mutationFn: () => api.post("/api/youtube/imports/clear"), onSuccess: refresh });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (url.trim()) start.mutate(url.trim());
  };
  const batches = groupByBatch(data ?? []);

  return (
    <section className="mb-8 max-w-4xl" data-testid="yt-imports">
      <div className="mb-2 flex items-center gap-3">
        <h2 className="text-lg font-bold">From YouTube</h2>
        <div className="flex-1" />
        {(data ?? []).some((i) => i.status === "in_library" || i.track?.status === "done") && (
          <Button variant="ghost" size="sm" onClick={() => clear.mutate()}><Trash2 /> Clear downloaded</Button>
        )}
      </div>
      <form onSubmit={submit} className="flex gap-2">
        <div className="relative flex-1">
          <TvMinimalPlay className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Link to a YouTube video or playlist"
            className="h-10 pl-9"
            data-testid="yt-url"
          />
        </div>
        <Button type="submit" className="h-10" disabled={!url.trim() || start.isPending} data-testid="yt-download">
          {start.isPending ? <Loader2 className="animate-spin" /> : <Download />} <span className="max-md:hidden">Download</span>
        </Button>
      </form>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {start.error ? (
          <span className="text-destructive">{(start.error as Error).message}</span>
        ) : start.data ? (
          started(start.data)
        ) : (
          "A video downloads just that song, a playlist every song in it. Songs are looked up on MusicBrainz and tagged from there; if no match is certain, you choose."
        )}
      </p>
      {batches.map((b) => (
        <Batch key={b.key} items={b.items} onChange={refresh} />
      ))}
    </section>
  );
}

function started(s: YTImportStarted) {
  if (s.kind === "video") return s.queued ? "Looking the video up on MusicBrainz…" : "That video is already here.";
  const name = s.title ? `“${s.title}”` : "the playlist";
  if (!s.queued) return `Every video of ${name} is already here.`;
  return `Looking up ${s.queued} ${s.queued === 1 ? "video" : "videos"} of ${name} on MusicBrainz…`
    + (s.queued < s.total ? ` (${s.total - s.queued} already here)` : "");
}

/** Imports arrive newest first; keep each playlist together. */
function groupByBatch(items: YTImport[]) {
  const out = new Map<string, YTImport[]>();
  for (const i of items) out.set(i.batch, [...(out.get(i.batch) ?? []), i]);
  return [...out].map(([key, list]) => ({ key, items: list.sort((a, b) => a.position - b.position) }));
}

function Batch({ items, onChange }: { items: YTImport[]; onChange: () => void }) {
  const playlist = items.length > 1 || items[0].batch !== items[0].video_id;
  const [open, setOpen] = useState(true);
  const choose = items.filter((i) => i.status === "needs_review").length;
  const done = items.filter((i) => i.status === "in_library" || i.track?.status === "done").length;
  return (
    <div className="mt-4" data-testid="yt-batch">
      {playlist && (
        <button type="button" onClick={() => setOpen(!open)} className="mb-1 flex w-full items-center gap-2 px-3 text-left text-sm max-md:px-1">
          <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", !open && "-rotate-90")} />
          <span className="truncate font-semibold">{items[0].batch_title || "Playlist"}</span>
          <span className="shrink-0 text-muted-foreground">
            {done}/{items.length} in the library{choose > 0 && ` · ${choose} to choose`}
          </span>
        </button>
      )}
      {open && items.map((i) => <Item key={i.id} imp={i} onChange={onChange} />)}
    </div>
  );
}

function Item({ imp, onChange }: { imp: YTImport; onChange: () => void }) {
  const live = useLiveTrack(imp.track_id ?? "");
  const [choosing, setChoosing] = useState(false);
  const t = imp.track;
  const status = live?.status ?? t?.status;
  const act = (p: Promise<unknown>) => p.then(onChange);
  const retry = () => act(api.post(`/api/youtube/imports/${imp.id}/retry`));
  const remove = () => act(api.del(`/api/youtube/imports/${imp.id}`));
  const cover = imp.release_id
    ? coverUrl("release", imp.release_id, 250, t?.release_group_id)
    : `https://i.ytimg.com/vi/${imp.video_id}/mqdefault.jpg`;
  const ytLine = [imp.artists.join(", "), formatDuration(imp.duration ? imp.duration * 1000 : null)].filter(Boolean).join(" · ");

  return (
    <div className="rounded-md hover:bg-elevated/50" data-testid="yt-item" data-status={imp.status}>
      <div className="group flex items-center gap-3 px-3 py-2 max-md:gap-2 max-md:px-1">
        <Cover src={cover} className="h-10 w-10" rounded="rounded" />
        <div className="min-w-0 flex-1">
          {t ? (
            <>
              <div className="truncate text-sm">{t.title}</div>
              <div className="truncate text-xs text-muted-foreground">
                {t.artist}
                {t.album && <> · <Link className="hover:underline" to={`/album/${t.release_group_id}?release=${imp.release_id}`}>{t.album}</Link></>}
                {imp.status === "in_library" && " · already in the library"}
                {status === "downloading" && (live?.stage ?? t.stage) && ` · ${live?.stage ?? t.stage}`}
              </div>
            </>
          ) : (
            <>
              <div className="truncate text-sm">{imp.title || imp.video_id}</div>
              <div className="truncate text-xs text-muted-foreground">
                {imp.status === "resolving" && "Looking it up on MusicBrainz…"}
                {imp.status === "needs_review" && (
                  <span className="text-warning">
                    {imp.candidates.length ? "No sure match on MusicBrainz — choose the song" : imp.error ?? "Not found on MusicBrainz"}
                  </span>
                )}
                {imp.status === "failed" && <span className="text-destructive">{imp.error}</span>}
                {ytLine && <> · {ytLine}</>}
              </div>
            </>
          )}
        </div>
        <a
          href={watchUrl(imp.video_id)}
          target="_blank"
          rel="noreferrer"
          title={`On YouTube: ${imp.title}`}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted-foreground opacity-0 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <ExternalLink className="h-4 w-4" />
        </a>
        <button
          type="button"
          onClick={remove}
          aria-label="Remove from the list"
          title="Remove from the list"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted-foreground opacity-0 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <X className="h-4 w-4" />
        </button>
        {imp.status === "resolving" && <Loader2 className="h-[18px] w-[18px] shrink-0 animate-spin text-muted-foreground" />}
        {imp.status === "in_library" && <CheckCircle2 className="h-[18px] w-[18px] shrink-0 text-primary" />}
        {imp.status === "matched" && status && (
          <TrackStatusButton
            status={status}
            progress={live?.progress ?? t?.progress}
            stage={live?.stage ?? t?.stage}
            error={live?.error ?? t?.error}
            onRetry={() => act(api.post(`/api/track/${imp.track_id}/retry`))}
          />
        )}
        {imp.status === "needs_review" && (
          <Button variant="secondary" size="sm" onClick={() => setChoosing(!choosing)} data-testid="yt-choose">
            Choose <ChevronDown className={cn("transition-transform", choosing && "rotate-180")} />
          </Button>
        )}
        {imp.status === "failed" && (
          <Button variant="secondary" size="sm" onClick={retry}><RotateCw /> Retry</Button>
        )}
      </div>
      {choosing && imp.status === "needs_review" && <Chooser imp={imp} onChosen={onChange} />}
    </div>
  );
}

interface Option {
  key: string;
  recording_id: string;
  release_id: string | null;
  title: string;
  artist: string;
  detail: string;
}

function fromCandidate(c: MBCandidate): Option {
  return {
    key: `c-${c.recording_id}`,
    recording_id: c.recording_id,
    release_id: c.release_id,
    title: c.title,
    artist: c.artist,
    detail: [c.disambiguation, c.release_title, c.date?.slice(0, 4), formatDuration(c.length_ms), `${Math.round(c.score * 100)}%`]
      .filter(Boolean).join(" · "),
  };
}

/** The recordings closest to the video, and a MusicBrainz search for when none is right. */
function Chooser({ imp, onChosen }: { imp: YTImport; onChosen: () => void }) {
  const [q, setQ] = useState(() => [imp.artists[0], imp.title].filter(Boolean).join(" "));
  const [submitted, setSubmitted] = useState<string | null>(null);
  const search = useQuery({
    queryKey: ["search", "track", submitted],
    queryFn: () => api.get<SearchResult>(`/api/search?type=track&limit=10&q=${encodeURIComponent(submitted ?? "")}`),
    enabled: !!submitted,
  });
  const pick = useMutation({
    mutationFn: (o: Option) => api.post(`/api/youtube/imports/${imp.id}/match`, { recording_id: o.recording_id, release_id: o.release_id }),
    onSuccess: onChosen,
  });
  const found: Option[] = (search.data?.tracks ?? []).map((h) => ({
    key: `s-${h.id}`,
    recording_id: h.id,
    release_id: h.release?.id ?? null,
    title: h.title,
    artist: h.artist,
    detail: [h.disambiguation, h.release?.title, h.release?.date?.slice(0, 4), formatDuration(h.length_ms)].filter(Boolean).join(" · "),
  }));
  const list = (options: Option[]) =>
    options.map((o) => (
      <div key={o.key} className="flex items-center gap-3 rounded px-2 py-1.5 hover:bg-elevated">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm">{o.title} <span className="text-muted-foreground">— {o.artist}</span></div>
          <div className="truncate text-xs text-muted-foreground">{o.detail}</div>
        </div>
        <Button size="sm" variant="secondary" disabled={pick.isPending} onClick={() => pick.mutate(o)} data-testid="yt-use">
          {pick.isPending && pick.variables?.key === o.key ? <Loader2 className="animate-spin" /> : <Download />} Use
        </Button>
      </div>
    ));

  return (
    <div className="mx-3 mb-3 ml-16 rounded-md border p-2 max-md:mx-1 max-md:ml-1" data-testid="yt-chooser">
      {imp.candidates.length > 0 && (
        <>
          <div className="px-2 pb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Closest on MusicBrainz</div>
          {list(imp.candidates.map(fromCandidate))}
        </>
      )}
      <form
        className="relative mt-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim()) setSubmitted(q.trim());
        }}
      >
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" placeholder="Search MusicBrainz for the song" />
      </form>
      {search.isFetching && <Loader2 className="m-2 h-4 w-4 animate-spin" />}
      {submitted && search.data && found.length === 0 && <p className="px-2 py-1.5 text-sm text-muted-foreground">Nothing found.</p>}
      {list(found)}
      {pick.error && <p className="px-2 pt-1 text-xs text-destructive">{(pick.error as Error).message}</p>}
    </div>
  );
}
