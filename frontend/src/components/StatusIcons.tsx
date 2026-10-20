import { AlertTriangle, ArrowDownCircle, CheckCircle2, Clock, FileText, HelpCircle, Mic2, MicOff, RotateCw } from "lucide-react";
import type { AlbumStatus, LyricsStatus, TrackStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";

export function ProgressRing({ value, size = 18 }: { value: number; size?: number }) {
  const r = (size - 3) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0.03, Math.min(1, value || 0));
  return (
    <svg width={size} height={size} className="-rotate-90" aria-label={`${Math.round(v * 100)}%`}>
      <circle cx={size / 2} cy={size / 2} r={r} stroke="currentColor" strokeOpacity={0.25} strokeWidth={2.5} fill="none" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke="hsl(var(--primary))"
        strokeWidth={2.5}
        fill="none"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - v)}
        strokeLinecap="round"
        className="transition-[stroke-dashoffset] duration-300"
      />
    </svg>
  );
}

const stageLabel: Record<string, string> = {
  matching: "Matching",
  downloading: "Downloading",
  converting: "Converting",
  tagging: "Tagging",
  lyrics: "Fetching lyrics",
  done: "Done",
};

interface Props {
  status: TrackStatus;
  progress?: number;
  stage?: string | null;
  error?: string | null;
  onDownload?: () => void;
  onRetry?: () => void;
  onReview?: () => void;
}

export function TrackStatusButton({ status, progress = 0, stage, error, onDownload, onRetry, onReview }: Props) {
  const wrap = (tip: string, node: React.ReactNode) => (
    <Tooltip>
      <TooltipTrigger asChild>{node}</TooltipTrigger>
      <TooltipContent className="max-w-xs">{tip}</TooltipContent>
    </Tooltip>
  );
  const btn = "flex h-7 w-7 items-center justify-center rounded-full transition-colors";
  switch (status) {
    case "done":
      return wrap("Downloaded", <span className={cn(btn, "text-primary")}><CheckCircle2 className="h-[18px] w-[18px]" /></span>);
    case "queued":
      return wrap("Queued", <span className={cn(btn, "text-muted-foreground")}><Clock className="h-[18px] w-[18px]" /></span>);
    case "downloading":
      return wrap(
        `${stageLabel[stage ?? ""] ?? "Working"}${stage === "downloading" ? ` ${Math.round(progress * 100)}%` : ""}`,
        <span className={btn} data-testid="progress">
          <ProgressRing value={stage === "downloading" ? progress : stage === "matching" ? 0.05 : 0.95} />
        </span>,
      );
    case "failed":
      return wrap(
        `Failed${error ? `: ${error}` : ""} — click to retry`,
        <button onClick={(e) => { e.stopPropagation(); onRetry?.(); }} className={cn(btn, "text-destructive hover:bg-destructive/15")}>
          <span className="relative">
            <AlertTriangle className="h-[18px] w-[18px]" />
            <RotateCw className="absolute -bottom-1 -right-1.5 h-2.5 w-2.5" />
          </span>
        </button>,
      );
    case "needs_review":
      return wrap(
        "Low-confidence match — click to review",
        <button onClick={(e) => { e.stopPropagation(); onReview?.(); }} className={cn(btn, "text-warning hover:bg-warning/15")}>
          <HelpCircle className="h-[18px] w-[18px]" />
        </button>,
      );
    default:
      return wrap(
        "Download",
        <button
          onClick={(e) => { e.stopPropagation(); onDownload?.(); }}
          className={cn(btn, "text-muted-foreground hover:scale-110 hover:text-foreground")}
          aria-label="Download"
        >
          <ArrowDownCircle className="h-[18px] w-[18px]" />
        </button>,
      );
  }
}

export function LyricsIndicator({ status }: { status: LyricsStatus }) {
  const map: Record<LyricsStatus, { icon: React.ReactNode; tip: string; cls: string }> = {
    synced: { icon: <Mic2 className="h-3.5 w-3.5" />, tip: "Synced lyrics (.lrc)", cls: "text-primary" },
    plain: { icon: <FileText className="h-3.5 w-3.5" />, tip: "Plain lyrics (in tags)", cls: "text-sky-400" },
    instrumental: { icon: <MicOff className="h-3.5 w-3.5" />, tip: "Instrumental", cls: "text-muted-foreground" },
    not_found: { icon: <MicOff className="h-3.5 w-3.5" />, tip: "No lyrics found", cls: "text-muted-foreground/50" },
    none: { icon: null, tip: "", cls: "" },
  };
  const m = map[status];
  if (!m.icon) return <span className="inline-block w-3.5" />;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("inline-flex", m.cls)} data-lyrics={status}>{m.icon}</span>
      </TooltipTrigger>
      <TooltipContent>{m.tip}</TooltipContent>
    </Tooltip>
  );
}

export function AlbumStatusBadge({ status, compact }: { status: AlbumStatus; compact?: boolean }) {
  if (status === "none") return null;
  if (status === "complete") return <Badge>{compact ? "✓" : "Downloaded"}</Badge>;
  return <Badge variant="warning">{compact ? "partial" : "Partially downloaded"}</Badge>;
}
