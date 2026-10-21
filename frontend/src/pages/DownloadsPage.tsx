import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Loader2, RotateCw, Trash2 } from "lucide-react";
import { api, coverUrl, type DownloadItem } from "@/lib/api";
import { useLiveVersion } from "@/lib/live";
import { useLiveTrack } from "@/lib/live";
import { Button } from "@/components/ui/button";
import { Cover } from "@/components/Cover";
import { TrackStatusButton } from "@/components/StatusIcons";
import { YouTubeImports } from "@/components/YouTubeImports";

export function DownloadsPage() {
  const qc = useQueryClient();
  useLiveVersion();
  const { data, isLoading } = useQuery({
    queryKey: ["downloads"],
    queryFn: () => api.get<{ active: DownloadItem[]; recent: DownloadItem[] }>("/api/downloads"),
    refetchInterval: 5000,
  });
  const clear = useMutation({ mutationFn: () => api.post("/api/downloads/clear"), onSuccess: () => qc.invalidateQueries({ queryKey: ["downloads"] }) });
  const retryAll = useMutation({ mutationFn: () => api.post("/api/downloads/retry-failed"), onSuccess: () => qc.invalidateQueries({ queryKey: ["downloads"] }) });

  return (
    <div className="p-6 max-md:px-3 max-md:pt-4">
      <div className="mb-6 flex items-center gap-3 max-md:mb-4 max-md:gap-2">
        <h1 className="text-3xl font-extrabold max-md:text-2xl">Downloads</h1>
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={() => retryAll.mutate()} title="Retry failed" className="max-md:w-8 max-md:px-0">
          <RotateCw /> <span className="max-md:hidden">Retry failed</span>
        </Button>
        <Button variant="ghost" size="sm" onClick={() => clear.mutate()} title="Clear finished" className="max-md:w-8 max-md:px-0">
          <Trash2 /> <span className="max-md:hidden">Clear finished</span>
        </Button>
      </div>
      <YouTubeImports />
      {isLoading && <Loader2 className="animate-spin" />}
      <Section title="In progress" items={data?.active ?? []} empty="Nothing downloading." />
      <Section title="Recent" items={data?.recent ?? []} empty="No recent downloads." />
    </div>
  );
}

function Section({ title, items, empty }: { title: string; items: DownloadItem[]; empty: string }) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-lg font-bold">{title} <span className="text-sm font-normal text-muted-foreground">{items.length || ""}</span></h2>
      {items.length === 0 && <p className="text-sm text-muted-foreground">{empty}</p>}
      <div className="max-w-4xl">{items.map((d) => <Item key={`${d.job_id}-${d.track_id}`} d={d} />)}</div>
    </section>
  );
}

function Item({ d }: { d: DownloadItem }) {
  const live = useLiveTrack(d.track_id ?? "");
  const qc = useQueryClient();
  const status = live?.status ?? d.track_status ?? "queued";
  const retry = () => d.track_id && api.post(`/api/track/${d.track_id}/retry`).then(() => qc.invalidateQueries({ queryKey: ["downloads"] }));
  return (
    <div className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-elevated max-md:px-1" data-testid="download-item">
      <Cover src={d.release_id ? coverUrl("release", d.release_id, 250, d.release_group_id ?? undefined) : undefined} className="h-10 w-10" rounded="rounded" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{d.title}</div>
        <div className="truncate text-xs text-muted-foreground">
          {d.artist}
          {d.album && d.release_group_id && (
            <> · <Link className="hover:underline" to={`/album/${d.release_group_id}?release=${d.release_id}`}>{d.album}</Link></>
          )}
          {d.kind !== "download" && ` · ${d.kind.replace("_", " ")}`}
          {(live?.stage ?? d.stage) && status === "downloading" && ` · ${live?.stage ?? d.stage}`}
          {d.attempts > 0 && ` · attempt ${d.attempts + 1}`}
        </div>
        {(live?.error ?? d.error) && status === "failed" && <div className="truncate text-xs text-destructive">{live?.error ?? d.error}</div>}
      </div>
      <TrackStatusButton status={status} progress={live?.progress ?? d.progress} stage={live?.stage ?? d.stage} error={d.error} onRetry={retry} />
    </div>
  );
}
