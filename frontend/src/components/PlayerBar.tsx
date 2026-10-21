import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Loader2, MicVocal, Pause, Play, SkipBack, SkipForward, Volume1, Volume2, VolumeX } from "lucide-react";
import { api } from "@/lib/api";
import { usePlayer } from "@/lib/player";
import { parseLrc } from "@/lib/lrc";
import { cn, formatSeconds } from "@/lib/utils";
import { Slider } from "@/components/ui/slider";
import { Cover } from "./Cover";

interface LyricsResp {
  status: string;
  synced: string | null;
  plain: string | null;
}

export function PlayerBar({ compact, lyricsOpen, onToggleLyrics }: { compact: boolean; lyricsOpen: boolean; onToggleLyrics: () => void }) {
  const { current, audio, playing, setPlaying, toggle, next, prev, queue, index } = usePlayer();
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(() => Number(localStorage.getItem("volume") ?? 0.8));
  const [muted, setMuted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [seeking, setSeeking] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // phone-sized windows: the mini player opens a full-screen one
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const a = audio.current;
    if (!a || !current) return;
    a.src = `/api/stream/${current.recording_id}${current.release_id ? `?release=${current.release_id}` : ""}`;
    setErr(null);
    setTime(0);
    setDuration((current.length_ms ?? 0) / 1000);
    if (playing) void a.play().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.recording_id, current?.track_id]);

  useEffect(() => {
    if (audio.current) audio.current.volume = muted ? 0 : volume;
    localStorage.setItem("volume", String(volume));
  }, [volume, muted, audio]);

  const VolIcon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2;
  const shown = seeking ?? time;
  const hasNext = index + 1 < queue.length;
  const subtitle = err ? <span className="text-destructive">{err}</span> : current?.artist;

  const seekBar = (
    <Slider
      value={[shown]}
      max={duration || 1}
      step={0.5}
      disabled={!current}
      onValueChange={([v]) => setSeeking(v)}
      onValueCommit={([v]) => {
        if (audio.current) audio.current.currentTime = v;
        setSeeking(null);
      }}
    />
  );
  const playIcon = (size: string) =>
    loading ? <Loader2 className={cn(size, "animate-spin")} /> : playing ? <Pause className={cn(size, "fill-current")} /> : <Play className={cn(size, "ml-0.5 fill-current")} />;

  // Kept first and outside the layouts below, so switching between them doesn't interrupt playback.
  const element = (
    <audio
      ref={audio}
      preload="auto"
      onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
      onDurationChange={(e) => Number.isFinite(e.currentTarget.duration) && setDuration(e.currentTarget.duration)}
      onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)}
      onWaiting={() => setLoading(true)}
      onCanPlay={() => setLoading(false)}
      onPlaying={() => setLoading(false)}
      onEnded={() => (hasNext ? next() : setPlaying(false))}
      onError={() => {
        setLoading(false);
        if (current) setErr("Playback failed");
      }}
      data-testid="audio"
    />
  );

  if (compact) {
    if (!current) return element;
    return (
      <>
        {element}
        <div
          role="button"
          tabIndex={0}
          onClick={() => setExpanded(true)}
          onKeyDown={(e) => e.key === "Enter" && setExpanded(true)}
          className="relative mx-2 mb-1 mt-1.5 flex shrink-0 items-center gap-3 overflow-hidden rounded-md bg-elevated p-2 pr-1"
          data-testid="mini-player"
        >
          <Cover src={current.cover} className="h-10 w-10 shrink-0" rounded="rounded" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold" data-testid="now-playing">{current.title}</div>
            <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); toggle(); }}
            className="flex h-10 w-10 shrink-0 items-center justify-center"
            aria-label={playing ? "Pause" : "Play"}
            data-testid="play-toggle"
          >
            {playIcon("h-6 w-6")}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); next(); }}
            disabled={!hasNext}
            className="flex h-10 w-10 shrink-0 items-center justify-center disabled:opacity-40"
            aria-label="Next"
          >
            <SkipForward className="h-5 w-5 fill-current" />
          </button>
          <div className="absolute inset-x-2 bottom-0 h-0.5 overflow-hidden rounded-full bg-foreground/20">
            <div className="h-full bg-foreground" style={{ width: `${duration ? Math.min(100, (shown / duration) * 100) : 0}%` }} />
          </div>
        </div>
        {expanded && (
          <NowPlaying onClose={() => setExpanded(false)}>
            {(showLyrics) => (
              <>
                <div className="flex min-h-0 flex-1 items-center justify-center py-4">
                  {showLyrics ? (
                    <Lyrics className="h-full w-full overflow-y-auto px-1" big={false} />
                  ) : (
                    <Cover src={current.cover} className="w-full max-w-[min(100%,24rem)]" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-xl font-bold">{current.title}</div>
                  <div className="truncate text-muted-foreground">{subtitle}</div>
                </div>
                <div className="mt-4">{seekBar}</div>
                <div className="mt-1.5 flex justify-between text-[11px] tabular-nums text-muted-foreground">
                  <span>{formatSeconds(shown)}</span>
                  <span>{formatSeconds(duration)}</span>
                </div>
                <div className="mb-2 mt-2 flex items-center justify-center gap-10">
                  <button onClick={prev} className="text-foreground active:opacity-60" aria-label="Previous">
                    <SkipBack className="h-8 w-8 fill-current" />
                  </button>
                  <button
                    onClick={toggle}
                    className="flex h-16 w-16 items-center justify-center rounded-full bg-foreground text-background active:scale-95"
                    aria-label={playing ? "Pause" : "Play"}
                  >
                    {playIcon("h-7 w-7")}
                  </button>
                  <button onClick={next} disabled={!hasNext} className="text-foreground active:opacity-60 disabled:opacity-40" aria-label="Next">
                    <SkipForward className="h-8 w-8 fill-current" />
                  </button>
                </div>
              </>
            )}
          </NowPlaying>
        )}
      </>
    );
  }

  return (
    <>
      {element}
      <footer className="grid h-20 shrink-0 grid-cols-[1fr_2fr_1fr] items-center gap-4 px-2">
        <div className="flex min-w-0 items-center gap-3">
          {current && (
            <>
              <Cover src={current.cover} className="h-14 w-14 shrink-0" rounded="rounded" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold" data-testid="now-playing">{current.title}</div>
                <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
              </div>
            </>
          )}
        </div>

        <div className="flex flex-col items-center gap-1.5">
          <div className="flex items-center gap-5">
            <button onClick={prev} disabled={!current} className="text-muted-foreground hover:text-foreground disabled:opacity-40" aria-label="Previous">
              <SkipBack className="h-5 w-5 fill-current" />
            </button>
            <button
              onClick={toggle}
              disabled={!current}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-foreground text-background transition-transform hover:scale-105 disabled:opacity-40"
              aria-label={playing ? "Pause" : "Play"}
              data-testid="play-toggle"
            >
              {playIcon("h-4 w-4")}
            </button>
            <button onClick={next} disabled={!current || !hasNext} className="text-muted-foreground hover:text-foreground disabled:opacity-40" aria-label="Next">
              <SkipForward className="h-5 w-5 fill-current" />
            </button>
          </div>
          <div className="flex w-full max-w-xl items-center gap-2 text-[11px] tabular-nums text-muted-foreground">
            <span className="w-10 text-right">{formatSeconds(shown)}</span>
            {seekBar}
            <span className="w-10">{formatSeconds(duration)}</span>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 pr-2">
          <button
            onClick={onToggleLyrics}
            className={cn("text-muted-foreground hover:text-foreground", lyricsOpen && "text-primary")}
            aria-label="Lyrics"
          >
            <MicVocal className="h-4 w-4" />
          </button>
          <button onClick={() => setMuted(!muted)} className="text-muted-foreground hover:text-foreground" aria-label="Mute">
            <VolIcon className="h-4 w-4" />
          </button>
          <Slider className="w-28" value={[muted ? 0 : volume]} max={1} step={0.01} onValueChange={([v]) => { setVolume(v); setMuted(false); }} />
        </div>
      </footer>
    </>
  );
}

/** The full-screen player of phone-sized windows, with the cover or the lyrics. The phone's back gesture closes it. */
function NowPlaying({ onClose, children }: { onClose: () => void; children: (showLyrics: boolean) => React.ReactNode }) {
  const [showLyrics, setShowLyrics] = useState(false);
  const closed = useRef(onClose);
  closed.current = onClose;
  useEffect(() => {
    // an entry of its own, so "back" closes the player rather than leaving the page under it
    if (!window.history.state?.nowPlaying) window.history.pushState({ ...window.history.state, nowPlaying: true }, "");
    const onPop = () => closed.current();
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const close = () => (window.history.state?.nowPlaying ? window.history.back() : onClose());
  return (
    <div
      className="fixed inset-0 z-40 flex flex-col bg-gradient-to-b from-emerald-950 to-surface px-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-3 animate-in slide-in-from-bottom duration-200"
      data-testid="now-playing-full"
    >
      <div className="-mx-3 flex items-center justify-between">
        <button onClick={close} className="flex h-10 w-10 items-center justify-center" aria-label="Close player">
          <ChevronDown className="h-6 w-6" />
        </button>
        <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{showLyrics ? "Lyrics" : "Now playing"}</span>
        <button
          onClick={() => setShowLyrics(!showLyrics)}
          className={cn("flex h-10 w-10 items-center justify-center", showLyrics ? "text-primary" : "text-foreground")}
          aria-label="Lyrics"
          aria-pressed={showLyrics}
        >
          <MicVocal className="h-5 w-5" />
        </button>
      </div>
      {children(showLyrics)}
    </div>
  );
}

export function LyricsPanel() {
  return (
    <aside className="w-80 shrink-0 overflow-y-auto rounded-lg bg-gradient-to-b from-emerald-900/50 to-surface p-6 max-lg:hidden">
      <h3 className="mb-4 text-sm font-bold uppercase tracking-wider text-muted-foreground">Lyrics</h3>
      <Lyrics big />
    </aside>
  );
}

/** The current song's lyrics, following along when they're synced; scrolls the nearest scrolling ancestor. */
function Lyrics({ className, big }: { className?: string; big: boolean }) {
  const { current, audio } = usePlayer();
  const { data } = useQuery({
    queryKey: ["lyrics", current?.recording_id],
    queryFn: () => api.get<LyricsResp>(`/api/lyrics/${current!.recording_id}`),
    enabled: !!current,
  });
  const lines = useMemo(() => (data?.synced ? parseLrc(data.synced) : []), [data?.synced]);
  const [t, setT] = useState(0);
  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    const on = () => setT(a.currentTime);
    a.addEventListener("timeupdate", on);
    return () => a.removeEventListener("timeupdate", on);
  }, [audio, current]);
  let active = -1;
  for (let i = 0; i < lines.length; i++) if (lines[i].time <= t + 0.25) active = i;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector(`[data-line="${active}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  return (
    <div className={className} ref={ref}>
      {!current && <p className="text-sm text-muted-foreground">Nothing playing.</p>}
      {current && !data?.synced && !data?.plain && <p className="text-sm text-muted-foreground">No lyrics available{data?.status === "instrumental" ? " (instrumental)" : ""}.</p>}
      {lines.length > 0 ? (
        <div className={cn("space-y-3", big ? "pb-40" : "py-[30%]")}>
          {lines.map((l, i) => (
            <p
              key={i}
              data-line={i}
              onClick={() => audio.current && (audio.current.currentTime = l.time)}
              className={cn(
                "cursor-pointer text-xl font-bold leading-snug transition-colors",
                !big && "text-2xl",
                i === active ? "text-foreground" : i < active ? "text-foreground/40" : "text-foreground/25 hover:text-foreground/60",
              )}
            >
              {l.text || "♪"}
            </p>
          ))}
        </div>
      ) : (
        data?.plain && <pre className="whitespace-pre-wrap font-sans text-base font-semibold leading-relaxed text-foreground/80">{data.plain}</pre>
      )}
    </div>
  );
}
