import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowDownCircle, Loader2, MicVocal, Play, RefreshCw, Tags } from "lucide-react";
import { useState } from "react";
import { api, coverUrl, isLocal, type ReleaseDetail, type ReleaseGroupDetail, type TrackRowData } from "@/lib/api";
import { useTrackActions } from "@/lib/actions";
import { useLiveVersion } from "@/lib/live";
import { usePlayer } from "@/lib/player";
import { formatDuration } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { AlbumStatusBadge } from "@/components/StatusIcons";
import { Cover } from "@/components/Cover";
import { Plays } from "@/components/Plays";
import { TrackList } from "@/components/TrackList";
import { TrackDrawer } from "@/components/TrackDrawer";
import { SyncToggle } from "@/components/SyncToggle";
import { FloatingBack } from "@/components/Sidebar";

export function AlbumPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const wanted = params.get("release") ?? undefined;
  const rg = useQuery({
    queryKey: ["release-group", id, wanted],
    queryFn: () => api.get<ReleaseGroupDetail>(`/api/release-group/${id}${wanted ? `?release=${wanted}` : ""}`),
  });
  const releaseId = wanted ?? rg.data?.selected_release_id;
  const rel = useQuery({
    queryKey: ["release", releaseId],
    queryFn: () => api.get<ReleaseDetail>(`/api/release/${releaseId}`),
    enabled: !!releaseId,
  });
  const actions = useTrackActions(releaseId);
  const player = usePlayer();
  const [open, setOpen] = useState<TrackRowData | null>(null);
  useLiveVersion();

  if (rg.isLoading || (releaseId && rel.isLoading))
    return <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin" /></div>;
  if (rg.error || rel.error) return <div className="p-8 text-destructive">{((rg.error ?? rel.error) as Error).message}</div>;
  if (!rg.data || !rel.data) return null;
  const r = rel.data;
  const g = rg.data;
  const lib = r.library;
  const cover = coverUrl("release", r.id, 500, g.id);
  // files without MusicBrainz ids: nothing to download, match or retag, and a single "edition"
  const local = isLocal(r.id);

  const playFrom = (i: number) =>
    player.playList(
      r.tracks.map((t) => ({
        recording_id: t.recording_id,
        track_id: t.track_id,
        release_id: r.id,
        title: t.title,
        artist: t.artist,
        length_ms: t.length_ms,
        cover: coverUrl("release", r.id, 250, g.id),
      })),
      i,
    );

  return (
    <div className="pb-10">
      <FloatingBack />
      <header className="relative flex items-end gap-6 overflow-hidden bg-gradient-to-b from-neutral-500/40 to-surface p-6 pt-16 max-md:flex-col max-md:items-stretch max-md:gap-4 max-md:px-4 max-md:pb-2 max-md:pt-14">
        <img src={cover} alt="" className="absolute inset-0 h-full w-full scale-125 object-cover opacity-25 blur-3xl" />
        <Cover src={coverUrl("release", r.id, 500, g.id)} className="relative w-52 shrink-0 shadow-2xl max-md:mx-auto max-md:w-48" alt={r.title} />
        <div className="relative min-w-0">
          <p className="text-sm font-semibold max-md:hidden">{g.primary_type ?? "Release"}</p>
          <h1 className="break-words text-4xl font-black tracking-tight max-md:text-2xl md:text-6xl" data-testid="album-title">{r.title}</h1>
          <p className="mt-4 flex flex-wrap items-center gap-x-1.5 text-sm max-md:mt-2">
            {r.artist_id && !isLocal(r.artist_id) ? <Link to={`/artist/${r.artist_id}`} className="font-bold hover:underline">{r.artist}</Link> : <b>{r.artist}</b>}
            <span className="text-muted-foreground">• {g.year ?? r.date?.slice(0, 4)} • {r.tracks.length} songs, {formatDuration(r.length_ms)}</span>
            <Plays n={g.plays} className="ml-1 text-sm" />
            <span className="ml-2"><AlbumStatusBadge status={lib.status} /></span>
            {lib.status !== "none" && <span className="text-xs text-muted-foreground">{lib.done}/{lib.total}</span>}
          </p>
          {g.genres.length > 0 && <p className="mt-1 text-xs text-muted-foreground">{g.genres.join(", ")}</p>}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-4 px-6 py-5 max-md:gap-2 max-md:px-4 max-md:py-3">
        <button
          onClick={() => playFrom(0)}
          className="flex h-14 w-14 items-center justify-center rounded-full bg-primary text-black shadow-lg transition-transform hover:scale-105 max-md:-order-2 max-md:h-12 max-md:w-12"
          aria-label="Play album"
        >
          <Play className="h-6 w-6 fill-current" />
        </button>
        {!local && (
          <Button
            variant="outline"
            onClick={() => actions.downloadAlbum.mutate(r.id)}
            disabled={actions.downloadAlbum.isPending || lib.status === "complete"}
            className="max-md:h-8 max-md:px-3 max-md:text-xs"
            data-testid="download-album"
          >
            {actions.downloadAlbum.isPending ? <Loader2 className="animate-spin" /> : <ArrowDownCircle />}
            {lib.status === "complete" ? "Downloaded" : lib.status === "partial" ? "Download remaining" : "Download album"}
          </Button>
        )}
        {/* phones: the edition and play on the first line, the rest below */}
        <div className="hidden basis-full max-md:-order-1 max-md:block" />
        <SyncToggle variant="button" className="max-md:h-8 max-md:px-3 max-md:text-xs" target={{ kind: "album", id: r.id, title: r.title, subtitle: r.artist }} artistId={r.artist_id} />
        {lib.done > 0 && (
          <>
            {!local && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="sm" onClick={() => actions.retag.mutate(r.id)} disabled={actions.retag.isPending} aria-label="Refresh tags" className="max-md:w-8 max-md:px-0">
                    {actions.retag.isPending ? <Loader2 className="animate-spin" /> : <Tags />} <span className="max-md:hidden">Refresh tags</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Rewrite tags from fresh MusicBrainz data (no re-download)</TooltipContent>
              </Tooltip>
            )}
            <Button variant="ghost" size="sm" onClick={() => actions.albumLyrics.mutate(r.id)} disabled={actions.albumLyrics.isPending} title="Fetch missing lyrics" aria-label="Fetch missing lyrics" className="max-md:w-8 max-md:px-0">
              {actions.albumLyrics.isPending ? <Loader2 className="animate-spin" /> : <MicVocal />} <span className="max-md:hidden">Fetch missing lyrics</span>
            </Button>
          </>
        )}
        <div className="flex-1 max-md:hidden" />
        {!local && (
          <div className="w-72 max-md:-order-3 max-md:w-auto max-md:min-w-0 max-md:flex-1">
            <Select
              value={r.id}
              onValueChange={(v) => {
                const p = new URLSearchParams(params);
                p.set("release", v);
                setParams(p, { replace: true });
              }}
            >
              <SelectTrigger className="text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {g.editions.map((e) => (
                  <SelectItem key={e.id} value={e.id} className="text-xs">
                    {[e.date ?? "????", e.country, e.formats.join("+"), `${e.track_count} tr`, e.labels[0], e.disambiguation, e.status !== "Official" ? e.status : null]
                      .filter(Boolean)
                      .join(" · ")}
                    {e.id === g.canonical_release_id ? " ★" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        {rel.isFetching && <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>

      <TrackList
        releaseId={r.id}
        artistId={r.artist_id}
        albumTitle={r.title}
        tracks={r.tracks}
        onPlay={playFrom}
        onOpen={setOpen}
        onDownload={(t) => actions.download.mutate({ releaseId: r.id, trackId: t.track_id })}
        onRetry={(t) => actions.retry.mutate(t.track_id)}
      />
      <div className="px-10 pt-6 text-xs text-muted-foreground max-md:px-4">
        {r.date} {r.country && `· ${r.country}`} {r.labels.length > 0 && `· ${r.labels.join(", ")}`}
        {r.catalog_numbers.length > 0 && ` · ${r.catalog_numbers.join(", ")}`} {r.barcode && `· ${r.barcode}`}
      </div>
      <TrackDrawer track={open} releaseId={r.id} onClose={() => setOpen(null)} />
    </div>
  );
}
