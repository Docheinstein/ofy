import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, Disc3, Download, Eye, FileUp, Loader2, Music, Plug, Square, Upload, User, X, XCircle } from "lucide-react";
import { api, isLocal, type Settings, type SyncKind, type SyncListImport, type SyncStatus, type SyncSummary } from "@/lib/api";
import { useSyncSelection } from "@/lib/sync";
import { formatBytes } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

type SyncSettings = Pick<Settings, "sync_host" | "sync_user" | "sync_port" | "sync_path" | "sync_ssh_key" | "sync_password" | "sync_delete">;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[200px_1fr] sm:items-center">
      <div>
        <Label>{label}</Label>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div>{children}</div>
    </div>
  );
}

export function SyncPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-10 p-8 max-md:space-y-8 max-md:p-4">
      <div>
        <h1 className="text-3xl font-extrabold max-md:text-2xl">Sync</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Copy the artists, albums and songs you mark with the cloud button to another computer (over SSH, with rsync)
          or to a folder such as a mounted drive.
        </p>
      </div>
      <Run />
      <Selection />
      <Destination />
    </div>
  );
}

function Destination() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
  const [form, setForm] = useState<SyncSettings | null>(null);
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);
  const save = useMutation({
    mutationFn: (f: SyncSettings) => api.put<Settings>("/api/settings", { ...data, ...f }),
    onSuccess: (s) => qc.setQueryData(["settings"], s),
  });
  const test = useMutation({
    mutationFn: async (f: SyncSettings) => {
      await save.mutateAsync(f);
      return api.post<{ ok: boolean; message: string }>("/api/sync/test");
    },
  });
  if (!form) return null;
  const set = <K extends keyof SyncSettings>(k: K, v: SyncSettings[K]) => setForm({ ...form, [k]: v });
  const local = !form.sync_host.trim();

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(form);
      }}
    >
      <h2 className="text-lg font-bold">Destination</h2>
      <Field label="Host" hint="Name or IP of the remote computer. Leave empty to sync to a local folder.">
        <Input value={form.sync_host} placeholder="192.168.1.20 or nas.local" onChange={(e) => set("sync_host", e.target.value)} data-testid="sync-host" />
      </Field>
      {!local && (
        <>
          <Field label="User">
            <Input value={form.sync_user} placeholder="Same as here" onChange={(e) => set("sync_user", e.target.value)} />
          </Field>
          <Field label="Password" hint="Leave empty to log in with an SSH key. Saved on this computer in plain text.">
            <Input
              type="password"
              autoComplete="new-password"
              value={form.sync_password}
              placeholder="SSH key login"
              onFocus={(e) => e.target.select()}
              onChange={(e) => set("sync_password", e.target.value)}
            />
          </Field>
          <Field label="SSH port">
            <Input type="number" min={1} max={65535} value={form.sync_port} onChange={(e) => set("sync_port", Number(e.target.value))} />
          </Field>
        </>
      )}
      <Field label="Folder" hint={local ? "Created if missing" : "On the remote; relative paths start from the user's home. Created if missing."}>
        <Input value={form.sync_path} placeholder={local ? "/media/usb/Music" : "~/Music/Ofy"} onChange={(e) => set("sync_path", e.target.value)} data-testid="sync-path" />
      </Field>
      {!local && (
        <Field label="SSH key" hint="Optional; defaults to your usual SSH keys. Without a password, set up a key with ssh-copy-id.">
          <Input value={form.sync_ssh_key} placeholder="~/.ssh/id_ed25519" onChange={(e) => set("sync_ssh_key", e.target.value)} />
        </Field>
      )}
      <Field label="Mirror the selection" hint="Delete files in the destination folder that aren't selected. Use a folder only Ofy writes to.">
        <Switch checked={form.sync_delete} onCheckedChange={(v) => set("sync_delete", v)} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : save.isSuccess ? <Check /> : null} Save
        </Button>
        <Button type="button" variant="outline" onClick={() => test.mutate(form)} disabled={test.isPending} data-testid="sync-test">
          {test.isPending ? <Loader2 className="animate-spin" /> : <Plug />} Test connection
        </Button>
        {test.data && (
          <span className={`flex items-center gap-1.5 text-sm ${test.data.ok ? "text-primary" : "text-destructive"}`}>
            {test.data.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />} {test.data.message}
          </span>
        )}
        {(save.error || test.error) && <span className="text-sm text-destructive">{((save.error ?? test.error) as Error).message}</span>}
      </div>
    </form>
  );
}

const KIND_ICON = { artist: User, album: Disc3, track: Music } as const;
const KIND_LABEL: Record<SyncKind, string> = { artist: "Artists", album: "Albums", track: "Songs" };

function Selection() {
  const sel = useSyncSelection();
  const { data: summary } = useQuery({
    queryKey: ["sync-summary"],
    queryFn: () => api.get<SyncSummary>("/api/sync/summary"),
  });
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold">Selected for sync</h2>
        <ListFile />
      </div>
      {summary && (
        <p className="text-sm text-muted-foreground" data-testid="sync-summary">
          {summary.tracks} songs · {summary.files} files · {formatBytes(summary.bytes)}
          {summary.pending > 0 && ` · ${summary.pending} selected songs aren't downloaded yet`}
          {summary.outside > 0 && ` · ${summary.outside} files outside the library folder are skipped`}
        </p>
      )}
      {sel.items.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing selected yet. Use the cloud button on an artist, album or song (in the <Link to="/library" className="underline">Library</Link> or
          on their pages); choosing an artist or album includes everything in it.
        </p>
      )}
      {(["artist", "album", "track"] as const).map((kind) => {
        const items = sel.items.filter((i) => i.kind === kind);
        if (!items.length) return null;
        const Icon = KIND_ICON[kind];
        return (
          <div key={kind}>
            <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">{KIND_LABEL[kind]}</h3>
            <div className="flex flex-col">
              {items.map((i) => (
                <div key={i.ref_id} className="group flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-elevated">
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1 truncate text-sm">
                    {kind === "artist" && !isLocal(i.ref_id) ? (
                      <Link to={`/artist/${i.ref_id}`} className="font-semibold hover:underline">{i.title || i.ref_id}</Link>
                    ) : (
                      <span className="font-semibold">{i.title || i.ref_id}</span>
                    )}
                    {kind !== "artist" && i.subtitle && <span className="text-muted-foreground"> · {i.subtitle}</span>}
                  </div>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={`Stop syncing ${i.title}`}
                    onClick={() => sel.set({ kind: i.kind, id: i.ref_id, title: i.title }, false)}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

/** The selection as a list of folders and files relative to the library, one per line, the way
 * rsync's --files-from reads it: saved to a file, or read back from one (replacing the selection). */
function ListFile() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const exportList = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/sync/selection/export");
      if (!res.ok) throw new Error(res.statusText);
      const url = URL.createObjectURL(new Blob([await res.text()], { type: "text/plain" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "ofy-sync.list";
      a.click();
      URL.revokeObjectURL(url);
    },
  });
  const importList = useMutation({
    mutationFn: async (file: File) => api.post<SyncListImport>("/api/sync/selection/import", { text: await file.text() }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["sync-selection"] });
      qc.invalidateQueries({ queryKey: ["sync-summary"] });
    },
  });
  const result = importList.data;
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => exportList.mutate()} disabled={exportList.isPending} data-testid="sync-export">
          <Download /> Export list
        </Button>
        <Button variant="outline" size="sm" onClick={() => input.current?.click()} disabled={importList.isPending} data-testid="sync-import">
          {importList.isPending ? <Loader2 className="animate-spin" /> : <FileUp />} Import list
        </Button>
        <input
          ref={input}
          type="file"
          accept=".list,.txt,text/plain"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file && window.confirm("Replace what's selected for sync with the artists, albums and songs in this list?")) {
              importList.mutate(file);
            }
          }}
        />
      </div>
      {(exportList.error || importList.error) && (
        <p className="text-sm text-destructive">{((exportList.error ?? importList.error) as Error).message}</p>
      )}
      {result && (
        <div className="text-right text-sm text-muted-foreground" data-testid="sync-import-result">
          <p>
            Selected {result.selected} {result.selected === 1 ? "item" : "items"} from the list
            {result.unmatched.length > 0 && `; ${result.unmatched.length} lines match nothing in the library and were left out:`}
          </p>
          {result.unmatched.length > 0 && (
            <div className="mt-1 max-h-40 overflow-y-auto rounded bg-black/30 p-2 text-left font-mono text-xs">
              {result.unmatched.map((l) => <div key={l}>{l}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Run() {
  const qc = useQueryClient();
  const { data: st } = useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.get<SyncStatus>("/api/sync/status"),
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });
  const run = useMutation({
    mutationFn: (dryRun: boolean) => api.post<SyncStatus>("/api/sync/run", { dry_run: dryRun }),
    onSuccess: (s) => qc.setQueryData(["sync-status"], s),
  });
  const cancel = useMutation({ mutationFn: () => api.post("/api/sync/cancel") });
  const running = !!st?.running;

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-bold">Transfer</h2>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => run.mutate(false)} disabled={running || run.isPending} data-testid="sync-run">
          {running && !st?.dry_run ? <Loader2 className="animate-spin" /> : <Upload />} Sync now
        </Button>
        <Button variant="outline" onClick={() => run.mutate(true)} disabled={running || run.isPending} data-testid="sync-preview">
          {running && st?.dry_run ? <Loader2 className="animate-spin" /> : <Eye />} Preview changes
        </Button>
        {running && (
          <Button variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            <Square /> Cancel
          </Button>
        )}
      </div>
      {run.error && <p className="text-sm text-destructive">{(run.error as Error).message}</p>}
      {st && st.started_at && <RunStatus st={st} />}
    </section>
  );
}

function RunStatus({ st }: { st: SyncStatus }) {
  const what = st.dry_run ? "Preview" : "Sync";
  return (
    <div className="space-y-3 rounded-lg bg-elevated p-4" data-testid="sync-status">
      {st.running ? (
        <>
          <div className="flex items-center justify-between text-sm">
            <span className="font-semibold">{st.dry_run ? "Checking what would change…" : "Syncing…"}</span>
            <span className="tabular-nums text-muted-foreground">{[st.speed, st.eta && st.eta !== "0:00:00" ? `${st.eta} left` : ""].filter(Boolean).join(" · ")}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${st.percent}%` }} />
          </div>
        </>
      ) : st.ok ? (
        <p className="flex items-center gap-2 text-sm font-semibold">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          {st.dry_run
            ? `Preview: ${st.transferred} files would be copied, ${st.deleted} deleted`
            : `${what} complete: ${st.transferred} files copied, ${st.deleted} deleted`}
          {st.finished_at && <span className="font-normal text-muted-foreground">· {new Date(st.finished_at * 1000).toLocaleTimeString()}</span>}
        </p>
      ) : (
        <p className="flex items-start gap-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {what} failed: {st.error}
        </p>
      )}
      {!st.running && st.changes && st.changes.length > 0 && (
        <div className="max-h-72 overflow-y-auto rounded bg-black/30 p-3 font-mono text-xs leading-relaxed">
          {st.changes.map((c, i) => (
            <div key={i} className={c.startsWith("-") ? "text-destructive" : "text-muted-foreground"}>{c}</div>
          ))}
          {st.transferred + st.deleted > st.changes.length && (
            <div className="text-muted-foreground">… and {st.transferred + st.deleted - st.changes.length} more</div>
          )}
        </div>
      )}
    </div>
  );
}
