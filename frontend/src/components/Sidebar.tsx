import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Download, FolderSync, Library, Search, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useHistoryNav } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { lastSearch } from "@/pages/SearchPage";

const items = [
  { to: "/search", label: "Search", icon: Search },
  { to: "/library", label: "Library", icon: Library },
  { to: "/downloads", label: "Downloads", icon: Download },
  { to: "/sync", label: "Sync", icon: FolderSync },
  { to: "/settings", label: "Settings", icon: Settings },
];

/** The nav targets; Search links back to the last search rather than an empty one. Re-read on every navigation. */
function useNavItems() {
  useLocation();
  return items.map((it) => (it.to === "/search" && lastSearch ? { ...it, to: `/search?${lastSearch}` } : it));
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
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={label}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-4 rounded-md px-3 py-2 text-sm font-bold text-muted-foreground transition-colors hover:text-foreground max-lg:justify-center",
                  isActive && "bg-elevated text-foreground",
                )
              }
            >
              <Icon className="h-5 w-5" />
              <span className="max-lg:hidden">{label}</span>
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
      {navItems.map(({ to, label, icon: Icon }) => (
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
              <Icon className="h-6 w-6" strokeWidth={isActive ? 2.5 : 2} />
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
