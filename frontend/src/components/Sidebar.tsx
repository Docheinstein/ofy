import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Download, FolderSync, Library, Search, Settings, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDownloads, useHistoryNav } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { lastSearch } from "@/pages/SearchPage";

const items: { to: string; label: string; icon: LucideIcon; count?: number }[] = [
  { to: "/search", label: "Search", icon: Search },
  { to: "/library", label: "Library", icon: Library },
  { to: "/downloads", label: "Downloads", icon: Download },
  { to: "/sync", label: "Sync", icon: FolderSync },
  { to: "/settings", label: "Settings", icon: Settings },
];

/**
 * The nav targets; Search links back to the last search rather than an empty one (re-read on every navigation),
 * and Downloads carries the number of downloads in progress.
 */
function useNavItems() {
  useLocation();
  const active = useDownloads().data?.active.length ?? 0;
  return items.map((it) =>
    it.to === "/search" && lastSearch ? { ...it, to: `/search?${lastSearch}` }
    : it.to === "/downloads" ? { ...it, count: active }
    : it,
  );
}

/** The count as a dot on the icon, for the icon-only sidebar and the bottom tab bar. */
function CountBadge({ count, className }: { count?: number; className?: string }) {
  if (!count) return null;
  return (
    <span className={cn("absolute -right-2 -top-1.5 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] font-bold leading-4 text-primary-foreground", className)}>
      {count > 99 ? "99+" : count}
    </span>
  );
}

/** Narrower windows (below `lg`) get just the icons. */
export function Sidebar() {
  const navItems = useNavItems();
  return (
    <aside className="flex w-60 shrink-0 flex-col gap-2 max-lg:w-16">
      <div className="rounded-lg bg-surface px-3 py-4">
        <div className="mb-4 flex items-center gap-2 px-3 max-lg:flex-col max-lg:px-0">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="text-lg font-extrabold tracking-tight max-lg:hidden">Ofy</span>
          <div className="flex-1" />
          <HistoryArrows />
        </div>
        <nav className="flex flex-col gap-1">
          {navItems.map(({ to, label, icon: Icon, count }) => (
            <NavLink
              key={to}
              to={to}
              title={count ? `${label} (${count} in progress)` : label}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-4 rounded-md px-3 py-2 text-sm font-bold text-muted-foreground transition-colors hover:text-foreground max-lg:justify-center",
                  isActive && "bg-elevated text-foreground",
                )
              }
            >
              <span className="relative">
                <Icon className="h-5 w-5" />
                <CountBadge count={count} className="lg:hidden" />
              </span>
              <span className="max-lg:hidden">
                {label}
                {!!count && <span className="font-normal text-muted-foreground"> ({count})</span>}
              </span>
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="flex-1 rounded-lg bg-surface" />
    </aside>
  );
}

/** The sidebar of phone-sized windows: a tab bar at the bottom of the screen. */
export function BottomNav() {
  const navItems = useNavItems();
  return (
    <nav className="grid shrink-0 grid-cols-5 bg-black pb-[env(safe-area-inset-bottom)]" data-testid="bottom-nav">
      {navItems.map(({ to, label, icon: Icon, count }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              "flex flex-col items-center gap-1 pb-2 pt-2.5 text-[11px] font-semibold text-muted-foreground transition-colors active:text-foreground",
              isActive && "text-foreground",
            )
          }
        >
          {({ isActive }) => (
            <>
              <span className="relative">
                <Icon className="h-6 w-6" strokeWidth={isActive ? 2.5 : 2} />
                <CountBadge count={count} />
              </span>
              {label}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

/** Back button for phone-sized windows, which have no sidebar arrows; floats over the top of the page as it scrolls. */
export function FloatingBack({ fallback = "/search" }: { fallback?: string }) {
  const { canBack, back } = useHistoryNav();
  const navigate = useNavigate();
  return (
    <div className="sticky top-0 z-20 h-0 md:hidden">
      <button
        type="button"
        onClick={() => (canBack ? back() : navigate(fallback))}
        aria-label="Go back"
        className="absolute left-3 top-3 flex h-9 w-9 items-center justify-center rounded-full bg-black/50 text-foreground backdrop-blur active:bg-black/70"
      >
        <ChevronLeft className="h-5 w-5" />
      </button>
    </div>
  );
}

function HistoryArrows() {
  const { canBack, canForward, back, forward } = useHistoryNav();
  return (
    <div className="flex gap-1 max-lg:flex-col">
      <Button variant="secondary" size="iconsm" onClick={back} disabled={!canBack} aria-label="Go back" title="Go back">
        <ChevronLeft />
      </Button>
      <Button variant="secondary" size="iconsm" onClick={forward} disabled={!canForward} aria-label="Go forward" title="Go forward">
        <ChevronRight />
      </Button>
    </div>
  );
}
