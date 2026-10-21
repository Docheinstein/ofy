import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowDownCircle, CheckCircle2, Loader2, Play, Search } from "lucide-react";
import { api, coverUrl, type SearchResult, type TrackHit } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import { usePlayer } from "@/lib/player";
import { formatDuration } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlbumCard } from "@/components/AlbumCard";
import { ArtistAvatar } from "@/components/ArtistAvatar";
import { Cover } from "@/components/Cover";

type Kind = "all" | "artist" | "album" | "track";

/** The query string of the last search, so the Search tab can bring it back after visiting other pages. */
export let lastSearch = "";

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const kind = (params.get("type") as Kind) ?? "all";
  const dq = useDebounced(q.trim(), 450);
  const { data, isFetching, error } = useQuery({
    queryKey: ["search", dq, kind],
    queryFn: () => api.get<SearchResult>(`/api/search?q=${encodeURIComponent(dq)}&type=${kind}`),
    enabled: dq.length > 0,
  });
  useEffect(() => {
    lastSearch = params.toString();
  }, [params]);
  const update = (next: Record<string, string>) => {
    const p = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
  };

  return (
    <div className="p-6 max-md:p-4">
      <div className="sticky top-0 z-10 -mx-6 -mt-6 bg-surface/95 px-6 pb-4 pt-6 backdrop-blur max-md:-mx-4 max-md:-mt-4 max-md:px-4 max-md:pb-3 max-md:pt-4">
        <div className="relative max-w-xl">
          <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            value={q}
            onChange={(e) => update({ q: e.target.value })}
            placeholder="What do you want to listen to?"
            className="h-12 rounded-full border-none bg-elevated pl-12 text-base max-md:h-11"
            data-testid="search-input"
          />
          {/* centred by the wrapper: animate-spin's transform would override the icon's own translate */}
          {isFetching && (
            <span className="absolute right-4 top-1/2 -translate-y-1/2">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </span>
          )}
        </div>
        {dq && (
          <Tabs value={kind} onValueChange={(v) => update({ type: v === "all" ? "" : v })} className="mt-4 max-md:mt-3">
            <TabsList>
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="artist">Artists</TabsTrigger>
              <TabsTrigger value="album">Albums</TabsTrigger>
              <TabsTrigger value="track">Songs</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
      </div>

      {!dq && (
        <div className="mt-24 text-center text-muted-foreground max-md:mt-16">
          <Search className="mx-auto mb-4 h-12 w-12" />
          <p className="text-lg font-bold text-foreground">Search MusicBrainz</p>
          <p className="text-sm">Find artists, albums and songs to download.</p>
        </div>
      )}
      {error && <p className="mt-6 text-destructive">{(error as Error).message}</p>}

      {data?.artists && data.artists.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 text-2xl font-bold max-md:text-xl">Artists</h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-2 max-md:-mx-2 max-md:grid-cols-3 max-md:gap-0">
            {data.artists.map((a) => (
              <Link key={a.id} to={`/artist/${a.id}`} className="flex flex-col items-center gap-3 rounded-md p-3 text-center hover:bg-elevated max-md:gap-2 max-md:p-2" data-testid="artist-result">
                <ArtistAvatar id={a.id} className="w-full" />
                <div className="w-full min-w-0">
                  <div className="truncate text-sm font-bold">{a.name}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {[a.type ?? "Artist", a.country, a.disambiguation].filter(Boolean).join(" · ")}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {data?.tracks && data.tracks.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-2xl font-bold max-md:text-xl">Songs</h2>
          <div className="max-w-4xl max-md:-mx-3">
            {data.tracks.map((t, i) => <SongRow key={t.id} t={t} list={data.tracks!} index={i} />)}
          </div>
        </section>
      )}

      {data?.albums && data.albums.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-2xl font-bold max-md:text-xl">Albums</h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-1 max-md:-mx-2 max-md:grid-cols-2 max-md:gap-0">
            {data.albums.map((rg) => (
              <AlbumCard key={rg.id} rg={rg} subtitle={[rg.year, rg.primary_type, rg.artist].filter(Boolean).join(" • ")} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function SongRow({ t, list, index }: { t: TrackHit; list: TrackHit[]; index: number }) {
  const player = usePlayer();
  const qc = useQueryClient();
  const dl = useMutation({
    mutationFn: () => api.post(`/api/recording/${t.id}/download${t.release ? `?release=${t.release.id}` : ""}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["downloads"] }),
  });
  const play = () =>
    player.playList(
      list.map((x) => ({
        recording_id: x.id,
        title: x.title,
        artist: x.artist,
        length_ms: x.length_ms,
        release_id: x.release?.id,
        cover: x.release ? coverUrl("release", x.release.id, 250, x.release.release_group_id ?? undefined) : undefined,
      })),
      index,
    );
  return (
    <div className="group flex items-center gap-3 rounded-md px-3 py-2 hover:bg-elevated" onDoubleClick={play}>
      <button className="relative h-10 w-10 shrink-0" onClick={play} aria-label="Play">
        <Cover src={t.release ? coverUrl("release", t.release.id, 250, t.release.release_group_id ?? undefined) : undefined} rounded="rounded" />
        <span className="absolute inset-0 hidden items-center justify-center rounded bg-black/60 group-hover:flex">
          <Play className="h-4 w-4 fill-current" />
        </span>
      </button>
      <div className="min-w-0 flex-1">
        <div className="truncate">{t.title} {t.disambiguation && <span className="text-muted-foreground">({t.disambiguation})</span>}</div>
        <div className="truncate text-sm text-muted-foreground">
          {t.artist_id ? <Link className="hover:underline" to={`/artist/${t.artist_id}`}>{t.artist}</Link> : t.artist}
          {t.release && (
            <>
              {" · "}
              {t.release.release_group_id ? (
                <Link className="hover:underline" to={`/album/${t.release.release_group_id}?release=${t.release.id}`}>{t.release.title}</Link>
              ) : (
                t.release.title
              )}
            </>
          )}
        </div>
      </div>
      <span className="text-sm tabular-nums text-muted-foreground">{formatDuration(t.length_ms)}</span>
      <button
        className="flex h-7 w-7 items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-60"
        onClick={() => dl.mutate()}
        disabled={dl.isPending || dl.isSuccess}
        aria-label="Download"
        title={dl.isError ? (dl.error as Error).message : dl.isSuccess ? "Queued" : "Download"}
      >
        {dl.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : dl.isSuccess ? <CheckCircle2 className="h-[18px] w-[18px] text-primary" /> : <ArrowDownCircle className={dl.isError ? "h-[18px] w-[18px] text-destructive" : "h-[18px] w-[18px]"} />}
      </button>
    </div>
  );
}
