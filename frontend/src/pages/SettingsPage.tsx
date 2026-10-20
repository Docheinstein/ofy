import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2 } from "lucide-react";
import { api, type Settings } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[220px_1fr] sm:items-center">
      <div>
        <Label>{label}</Label>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div>{children}</div>
    </div>
  );
}

export function SettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
  const [form, setForm] = useState<Settings | null>(null);
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);
  const save = useMutation({
    mutationFn: (s: Settings) => api.put<Settings>("/api/settings", s),
    onSuccess: (s) => qc.setQueryData(["settings"], s),
  });

  if (!form) return <div className="p-8 text-muted-foreground">Loading…</div>;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setForm({ ...form, [k]: v });

  return (
    <div className="mx-auto max-w-3xl p-8">
      <h1 className="mb-8 text-3xl font-extrabold">Settings</h1>
      <form
        className="space-y-10"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(form);
        }}
      >
        <section className="space-y-5">
          <h2 className="text-lg font-bold">Library</h2>
          <Field label="Library path" hint="Root folder where music is saved">
            <Input value={form.library_path} onChange={(e) => set("library_path", e.target.value)} />
          </Field>
          <Field label="Path template" hint="Fields: albumartist, artist, album, title, year, disc, track, ext …">
            <Input
              className="font-mono text-xs"
              value={form.path_template}
              onChange={(e) => set("path_template", e.target.value)}
            />
          </Field>
        </section>

        <section className="space-y-5">
          <h2 className="text-lg font-bold">Audio</h2>
          <Field label="Output format">
            <Select value={form.output_format} onValueChange={(v) => set("output_format", v as Settings["output_format"])}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="mp3">MP3 (re-encode)</SelectItem>
                <SelectItem value="m4a">M4A / AAC (no re-encode when source is AAC)</SelectItem>
                <SelectItem value="opus">Opus (no re-encode)</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {form.output_format === "mp3" && (
            <Field label="MP3 quality">
              <Select value={form.mp3_quality} onValueChange={(v) => set("mp3_quality", v as Settings["mp3_quality"])}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="320">320 kbps CBR</SelectItem>
                  <SelectItem value="v0">V0 (VBR ~245 kbps)</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
        </section>

        <section className="space-y-5">
          <h2 className="text-lg font-bold">Downloads &amp; matching</h2>
          <Field label="Concurrent downloads">
            <Input
              type="number"
              min={1}
              max={8}
              value={form.concurrency}
              onChange={(e) => set("concurrency", Number(e.target.value))}
            />
          </Field>
          <Field label="Max retries">
            <Input
              type="number"
              min={0}
              max={10}
              value={form.max_retries}
              onChange={(e) => set("max_retries", Number(e.target.value))}
            />
          </Field>
          <Field label="Match threshold" hint="Matches below this confidence need review (0–1)">
            <Input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={form.match_threshold}
              onChange={(e) => set("match_threshold", Number(e.target.value))}
            />
          </Field>
          <Field label="cookies.txt path" hint="Optional, for age-restricted content">
            <Input value={form.cookies_path} placeholder="~/.config/ofy/cookies.txt" onChange={(e) => set("cookies_path", e.target.value)} />
          </Field>
        </section>

        <section className="space-y-5">
          <h2 className="text-lg font-bold">Lyrics</h2>
          <Field label="Fetch lyrics from LRCLIB">
            <Switch checked={form.lyrics_fetch} onCheckedChange={(v) => set("lyrics_fetch", v)} />
          </Field>
          <Field label="Prefer synced lyrics" hint="Save a .lrc when synced lyrics match the file's length; plain lyrics only go in the tags">
            <Switch checked={form.lyrics_prefer_synced} onCheckedChange={(v) => set("lyrics_prefer_synced", v)} />
          </Field>
          <Field label="Embed lyrics in tags">
            <Switch checked={form.lyrics_embed} onCheckedChange={(v) => set("lyrics_embed", v)} />
          </Field>
          <Field label="LRCLIB URL">
            <Input value={form.lrclib_url} onChange={(e) => set("lrclib_url", e.target.value)} />
          </Field>
        </section>

        <div className="flex items-center gap-4">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : save.isSuccess ? <Check /> : null}
            Save settings
          </Button>
          {save.isError && <span className="text-sm text-destructive">{(save.error as Error).message}</span>}
        </div>
      </form>
    </div>
  );
}
