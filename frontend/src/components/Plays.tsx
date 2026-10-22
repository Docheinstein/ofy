import { Headphones } from "lucide-react";
import { cn } from "@/lib/utils";

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

/** How many times it was played on ListenBrainz; nothing when unknown or ListenBrainz is off.
 * ``bare`` leaves out the icon, for a column with it in its header. */
export function Plays({ n, bare, className }: { n?: number | null; bare?: boolean; className?: string }) {
  if (n == null) return null;
  return (
    <span
      className={cn("inline-flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground", className)}
      title={`${n.toLocaleString("en")} plays on ListenBrainz`}
    >
      {!bare && <Headphones className="h-3 w-3" />}
      {compact.format(n)}
    </span>
  );
}
