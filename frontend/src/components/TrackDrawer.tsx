import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, Mic2, RefreshCw, Search } from "lucide-react";
import { useState } from "react";
import { api, ApiError, isLocal, type TrackDetail, type TrackRowData } from "@/lib/api";
import { useTrackActions } from "@/lib/actions";
import { useLiveTrack } from "@/lib/live";
import { cn, formatDuration, formatSeconds } from "@/lib/utils";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LyricsIndicator, TrackStatusButton } from "./StatusIcons";
import { TagEditor } from "./TagEditor";

/** What the drawer needs of a track: an album's track row, or a downloaded song in the library (no `library` state). */
export type DrawerTrack = Pick<TrackRowData, "track_id" | "title" | "artist" | "disc" | "position" | "length_ms"> &
  Partial<Pick<TrackRowData, "library">>;

export function TrackDrawer({ track, releaseId, onClose }: { track: DrawerTrack | null; releaseId: string; onClose: () => void }) {
  return (
    <Sheet open={!!track} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="overflow-y-auto">
        {track && <DrawerBody track={track} releaseId={releaseId} />}
      </SheetContent>
    </Sheet>
  );
}

function DrawerBody({ track, releaseId }: { track: DrawerTrack; releaseId: string }) {
  const qc = useQueryClient();
  const live = useLiveTrack(track.track_id);
  const { data, isLoading, error } = useQuery({
    queryKey: ["track", track.track_id, live?.status, live?.lyrics_status],
    queryFn: () => api.get<TrackDetail>(`/api/track/${track.track_id}`),
    retry: false,
  });
  const notInDb = error instanceof ApiError && error.status === 404;
  const actions = useTrackActions(releaseId);
  const [searching, setSearching] = useState(false);
  const status = live?.status ?? data?.status ?? track.library?.status ?? "none";
  const local = isLocal(track.track_id); // a file taken as it is: no YouTube match

  const findCandidates = async () => {
    setSearching(true);
    try {
      await api.post(`/api/release/${releaseId}/tracks/${track.track_id}/candidates`);
      await qc.invalidateQueries({ queryKey: ["track", track.track_id] });
    } finally {
      setSearching(false);
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle>{track.title}</SheetTitle>
        <SheetDescription>
          {track.artist} · Disc {track.disc} · Track {track.position} · {formatDuration(track.length_ms)}
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-wrap items-center gap-3">
        <TrackStatusButton
          status={status}
          progress={live?.progress ?? data?.progress}
          stage={live?.stage ?? data?.stage}
          error={live?.error ?? data?.error}
          onDownload={() => actions.download.mutate({ releaseId, trackId: track.track_id })}
          onRetry={() => actions.retry.mutate(track.track_id)}
        />
        <span className="text-sm capitalize text-muted-foreground">{status.replace("_", " ")}</span>
        {data?.match_score != null && (
          <Badge variant={data.match_score >= data.threshold ? "default" : "warning"}>
            {data.match_source} match · {(data.match_score * 100).toFixed(0)}%
          </Badge>
        )}
        {data?.video_id && (
          <a
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            href={`https://music.youtube.com/watch?v=${data.video_id}`}
            target="_blank"
            rel="noreferrer"
          >
            {data.video_id} <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {(data?.error ?? live?.error) && status === "failed" && (
        <p className="rounded-md bg-destructive/10 p-3 text-xs text-destructive">{data?.error ?? live?.error}</p>
      )}

      <Tabs defaultValue={status === "needs_review" ? "match" : "tags"}>
        <TabsList>
          <TabsTrigger value="tags">Tags</TabsTrigger>
          {!local && <TabsTrigger value="match">Match</TabsTrigger>}
          <TabsTrigger value="lyrics">Lyrics</TabsTrigger>
        </TabsList>

        <TabsContent value="tags">
          {isLoading && <Loader2 className="animate-spin" />}
          {notInDb && <p className="text-sm text-muted-foreground">Not downloaded yet.</p>}
          {data && !data.tags && <p className="text-sm text-muted-foreground">No file on disk yet.</p>}
          {data?.tags && (
            <div className="space-y-4">
              <p className="break-all font-mono text-xs text-muted-foreground">{data.file_path}</p>
              {data.fields && status === "done" && (
                <TagEditor key={JSON.stringify(data.fields)} trackId={track.track_id} fields={data.fields} editable={data.editable} />
              )}
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Raw tags in the file</summary>
                <table className="mt-2 w-full text-xs">
                  <tbody>
                    {Object.entries(data.tags).map(([k, v]) => (
                      <tr key={k} className="border-b border-border/50 align-top">
                        <td className="whitespace-nowrap py-1.5 pr-3 font-medium text-muted-foreground">{k}</td>
                        <td className="break-all py-1.5 font-mono">{v.join(" ; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </div>
          )}
        </TabsContent>

        <TabsContent value="match" className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Top YouTube Music candidates. {data ? `Threshold ${(data.threshold * 100).toFixed(0)}%.` : ""}
            </p>
            <Button size="sm" variant="secondary" onClick={findCandidates} disabled={searching}>
              {searching ? <Loader2 className="animate-spin" /> : <Search />} Find candidates
            </Button>
          </div>
          {data?.candidates.length === 0 && <p className="text-sm text-muted-foreground">No candidates yet.</p>}
          <div className="space-y-1">
            {data?.candidates.map((c) => {
              const chosen = c.video_id === data.video_id;
              return (
                <div
                  key={c.video_id}
                  className={cn("flex items-center gap-3 rounded-md p-2 hover:bg-elevated", chosen && "bg-primary/10 ring-1 ring-primary/40")}
                >
                  {c.thumbnail ? <img src={c.thumbnail} className="h-10 w-10 rounded object-cover max-sm:hidden" alt="" /> : <div className="h-10 w-10 rounded bg-elevated max-sm:hidden" />}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{c.title}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {c.artists.join(", ")}
                      {c.album ? ` · ${c.album}` : ""} · {c.duration != null ? formatSeconds(c.duration) : "?"} ·{" "}
                      {c.video_type === "MUSIC_VIDEO_TYPE_ATV" ? "Art track" : c.video_type ? "Video" : c.source}
                    </div>
                  </div>
                  <span className={cn("text-xs tabular-nums", c.score >= (data.threshold ?? 0.7) ? "text-primary" : "text-warning")}>
                    {(c.score * 100).toFixed(0)}%
                  </span>
                  <a href={`https://music.youtube.com/watch?v=${c.video_id}`} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-foreground">
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  <Button
                    size="sm"
                    variant={chosen ? "secondary" : "default"}
                    disabled={actions.choose.isPending}
                    onClick={() => actions.choose.mutate({ trackId: track.track_id, videoId: c.video_id })}
                  >
                    {chosen ? "Re-download" : "Use this"}
                  </Button>
                </div>
              );
            })}
          </div>
        </TabsContent>

        <TabsContent value="lyrics" className="space-y-3">
          <div className="flex items-center gap-2">
            <LyricsIndicator status={live?.lyrics_status ?? data?.lyrics_status ?? "none"} />
            <span className="text-sm capitalize text-muted-foreground">{(live?.lyrics_status ?? data?.lyrics_status ?? "none").replace("_", " ")}</span>
            <div className="flex-1" />
            <Button size="sm" variant="secondary" disabled={!data?.file_path || actions.lyrics.isPending} onClick={() => actions.lyrics.mutate(track.track_id)}>
              {actions.lyrics.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Fetch lyrics again
            </Button>
          </div>
          {data?.lyrics_path && <p className="break-all font-mono text-xs text-muted-foreground">{data.lyrics_path}</p>}
          {data?.lyrics_text ? (
            <pre className="whitespace-pre-wrap rounded-md bg-elevated p-4 font-sans text-sm leading-relaxed">{data.lyrics_text}</pre>
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted-foreground"><Mic2 className="h-4 w-4" /> No lyrics saved.</p>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}
