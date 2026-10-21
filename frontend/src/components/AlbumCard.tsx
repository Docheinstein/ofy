import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, CircleDashed } from "lucide-react";
import { coverUrl, type ReleaseGroupSummary } from "@/lib/api";
import { Cover } from "./Cover";
import { AlbumStatusBadge } from "./StatusIcons";

export function AlbumCard({ rg, subtitle, action }: { rg: ReleaseGroupSummary; subtitle?: string; action?: ReactNode }) {
  const status = rg.library?.status ?? "none";
  return (
    <Link
      to={`/album/${rg.id}`}
      className="group flex flex-col gap-2 rounded-md p-3 transition-colors hover:bg-elevated max-md:p-2"
    >
      <div className="relative">
        <Cover src={coverUrl("release-group", rg.id, 250)} alt={rg.title} />
        {action && <div className="absolute right-2 top-2">{action}</div>}
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
        </div>
      </div>
    </Link>
  );
}
