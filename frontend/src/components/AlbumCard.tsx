import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowDownCircle, CheckCircle2, CircleDashed, Loader2 } from "lucide-react";
import { api, coverUrl, type ReleaseGroupDetail, type ReleaseGroupSummary } from "@/lib/api";
import { Cover } from "./Cover";
import { Plays } from "./Plays";
import { AlbumStatusBadge } from "./StatusIcons";

export function AlbumCard({ rg, subtitle }: { rg: ReleaseGroupSummary; subtitle?: string }) {
  const status = rg.library?.status ?? "none";
  return (
    <Link
      to={`/album/${rg.id}`}
      className="group flex flex-col gap-2 rounded-md p-3 transition-colors hover:bg-elevated max-md:p-2"
    >
      <div className="relative">
        <Cover src={coverUrl("release-group", rg.id, 250)} alt={rg.title} />
        {status !== "complete" && (
          <div className="absolute right-2 top-2">
            <AlbumDownloadButton rg={rg} />
          </div>
        )}
        {status !== "none" && (
          <div className="absolute bottom-2 right-2 rounded-full bg-black/70 p-1">
            {status === "complete" ? (
              <CheckCircle2 className="h-5 w-5 text-primary" />
            ) : (
              <CircleDashed className="h-5 w-5 text-warning" />
            )}
          </div>
        )}
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-bold">{rg.title}</div>
        <div className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          <span className="truncate">{subtitle ?? [rg.year, rg.artist].filter(Boolean).join(" • ")}</span>
          {status === "partial" && <AlbumStatusBadge status={status} compact />}
          <Plays n={rg.plays} className="ml-auto" />
        </div>
      </div>
    </Link>
  );
}

// Queues the edition the album page would open with (the one already in the library, else the canonical one).
function AlbumDownloadButton({ rg }: { rg: ReleaseGroupSummary }) {
  const qc = useQueryClient();
  const dl = useMutation({
    mutationFn: async () => {
      const g = await api.get<ReleaseGroupDetail>(`/api/release-group/${rg.id}`);
      return api.post(`/api/release/${g.selected_release_id}/download`);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["downloads"] });
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["search"] });
      qc.invalidateQueries({ queryKey: ["artist"] });
    },
  });
  const label = dl.isError ? (dl.error as Error).message : dl.isSuccess ? "Queued" : rg.library?.status === "partial" ? "Download remaining" : "Download album";
  return (
    <button
      className={`flex h-9 w-9 items-center justify-center rounded-full bg-black/70 text-white shadow transition-opacity hover:scale-105 hover:bg-black/85 disabled:opacity-80 focus-visible:opacity-100 ${dl.isIdle ? "md:opacity-0 md:group-hover:opacity-100" : ""}`}
      onClick={(e) => {
        e.preventDefault(); // the card is a link to the album
        e.stopPropagation();
        dl.mutate();
      }}
      disabled={dl.isPending || dl.isSuccess}
      aria-label={label}
      title={label}
      data-testid="album-card-download"
    >
      {dl.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : dl.isSuccess ? <CheckCircle2 className="h-5 w-5 text-primary" /> : <ArrowDownCircle className={dl.isError ? "h-5 w-5 text-destructive" : "h-5 w-5"} />}
    </button>
  );
}
