import { CloudCheck, CloudUpload } from "lucide-react";
import type { MouseEvent } from "react";
import { type SyncTarget, useSyncSelection } from "@/lib/sync";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  target: SyncTarget;
  /** Ancestors, to show the item as already included when one of them is selected. */
  artistId?: string | null;
  releaseId?: string | null;
  /** More items of the same kind that go along with the target (the other editions of an album). */
  alsoIds?: string[];
  /** "button" shows a labelled button (page headers); "icon" a small round toggle (rows, cards). */
  variant?: "button" | "icon";
  /** Icon variant only: hide until the parent `group` is hovered while off. */
  hideWhenOff?: boolean;
  /** Icon variant only: just an indicator, shown only while on (crowded touch lists, where hover can't reveal it). */
  onlyWhenOn?: boolean;
  className?: string;
}

/** Marks an artist, album or track to be kept on the sync remote. */
export function SyncToggle({ target, artistId, releaseId, alsoIds = [], variant = "icon", hideWhenOff, onlyWhenOn, className }: Props) {
  const sel = useSyncSelection();
  const others = alsoIds.filter((id) => id !== target.id);
  const own = sel.has(target.kind, target.id) || others.some((id) => sel.has(target.kind, id));
  const via = own ? null : sel.inheritedFrom(target.kind === "artist" ? null : artistId, target.kind === "track" ? releaseId : null);
  const on = own || !!via;
  const label = via ? `Synced with the whole ${via}` : own ? "Synced to the remote — click to stop" : "Sync to the remote";
  const click = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (via) return;
    sel.set(target, !own);
    for (const id of others) if (sel.has(target.kind, id) === own) sel.set({ ...target, id }, !own);
  };
  const Icon = on ? CloudCheck : CloudUpload;
  if (onlyWhenOn && !on) return null;

  const trigger =
    variant === "button" ? (
      <Button variant={on ? "secondary" : "outline"} onClick={click} disabled={!!via} data-testid="sync-toggle" data-on={on}
        className={cn(on && "text-primary", className)}>
        <Icon /> {on ? "Synced" : "Sync"}
      </Button>
    ) : (
      <button
        type="button"
        onClick={click}
        aria-label={label}
        aria-pressed={on}
        data-testid="sync-toggle"
        data-on={on}
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
          on ? "text-primary" : "text-muted-foreground hover:text-foreground",
          via && "cursor-default opacity-60",
          !on && hideWhenOff && "opacity-0 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100",
          className,
        )}
      >
        <Icon className="h-[18px] w-[18px]" />
      </button>
    );
  return (
    <Tooltip>
      <TooltipTrigger asChild>{via && variant === "button" ? <span tabIndex={0}>{trigger}</span> : trigger}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
