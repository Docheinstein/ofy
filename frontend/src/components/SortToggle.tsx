import { useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";

export type Sort = "year" | "plays";

/** ?sort=plays, kept in the URL so it survives going back from an album; by year otherwise. */
export function useSort(): [Sort, (s: Sort) => void] {
  const [params, setParams] = useSearchParams();
  const sort: Sort = params.get("sort") === "plays" ? "plays" : "year";
  const setSort = (s: Sort) => {
    const next = new URLSearchParams(params);
    if (s === "year") next.delete("sort");
    else next.set("sort", s);
    setParams(next, { replace: true });
  };
  return [sort, setSort];
}

/** Most played first; the ones without a count keep their order after them. */
export function byPlays<T extends { plays?: number | null }>(items: T[]): T[] {
  return [...items].sort((a, b) => (b.plays ?? -1) - (a.plays ?? -1));
}

export function SortToggle({ sort, onChange, className }: { sort: Sort; onChange: (s: Sort) => void; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)} role="group" aria-label="Sort by">
      <span className="text-sm text-muted-foreground">Sort by</span>
      {(["year", "plays"] as const).map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onChange(s)}
          aria-pressed={sort === s}
          data-testid={`sort-${s}`}
          className={cn(
            "rounded-full px-3 py-1 text-sm font-semibold transition-colors",
            sort === s ? "bg-foreground text-background" : "bg-elevated text-foreground hover:bg-elevated/70",
          )}
        >
          {s === "year" ? "Year" : "Plays"}
        </button>
      ))}
    </div>
  );
}
