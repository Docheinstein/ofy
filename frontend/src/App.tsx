import { type RefObject, useLayoutEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigationType } from "react-router-dom";
import { BottomNav, Sidebar } from "@/components/Sidebar";
import { LyricsPanel, PlayerBar } from "@/components/PlayerBar";
import { PlayerProvider } from "@/lib/player";
import { useLiveUpdates } from "@/lib/live";
import { useCompact } from "@/lib/hooks";
import { SearchPage } from "@/pages/SearchPage";
import { ArtistPage } from "@/pages/ArtistPage";
import { AlbumPage } from "@/pages/AlbumPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { DownloadsPage } from "@/pages/DownloadsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SyncPage } from "@/pages/SyncPage";

/** All pages scroll in the same element: start new pages at the top, and put back where each one was when going back. */
function useScrollMemory(ref: RefObject<HTMLElement>) {
  const location = useLocation();
  const type = useNavigationType();
  const saved = useRef(new Map<string, number>());
  const key = useRef(location.key);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => saved.current.set(key.current, el.scrollTop);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [ref]);
  useLayoutEffect(() => {
    key.current = location.key;
    const el = ref.current;
    if (!el || type === "REPLACE") return;
    el.scrollTop = type === "POP" ? saved.current.get(location.key) ?? 0 : 0;
  }, [location.key, type, ref]);
}

export default function App() {
  useLiveUpdates();
  const compact = useCompact();
  const [lyricsOpen, setLyricsOpen] = useState(false);
  const main = useRef<HTMLElement>(null);
  useScrollMemory(main);
  return (
    <PlayerProvider>
      <div className="flex h-full flex-col gap-2 bg-black p-2 max-md:gap-0 max-md:p-0">
        <div className="flex min-h-0 flex-1 gap-2">
          {!compact && <Sidebar />}
          <main ref={main} className="min-w-0 flex-1 overflow-y-auto overscroll-contain rounded-lg bg-surface max-md:rounded-none">
            <Routes>
              <Route path="/" element={<Navigate to="/search" replace />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/artist/:id" element={<ArtistPage />} />
              <Route path="/album/:id" element={<AlbumPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/downloads" element={<DownloadsPage />} />
              <Route path="/sync" element={<SyncPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/search" replace />} />
            </Routes>
          </main>
          {lyricsOpen && !compact && <LyricsPanel />}
        </div>
        <PlayerBar compact={compact} lyricsOpen={lyricsOpen} onToggleLyrics={() => setLyricsOpen(!lyricsOpen)} />
        {compact && <BottomNav />}
      </div>
    </PlayerProvider>
  );
}
