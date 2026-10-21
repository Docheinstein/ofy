import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save, Undo2, X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const LABELS: Record<string, string> = {
  title: "Title",
  artist: "Artist",
  artists: "Artists",
  album: "Album",
  albumartist: "Album artist",
  albumartists: "Album artists",
  artistsort: "Artist sort order",
  albumartistsort: "Album artist sort order",
  tracknumber: "Track number",
  totaltracks: "Total tracks",
  discnumber: "Disc number",
  totaldiscs: "Total discs",
  date: "Date",
  originaldate: "Original date",
  originalyear: "Original year",
  genre: "Genre",
  label: "Record label",
  catalognumber: "Catalog number",
  barcode: "Barcode",
  isrc: "ISRC",
  media: "Media",
  releasetype: "Release type",
  releasestatus: "Release status",
  releasecountry: "Release country",
  compilation: "Compilation (1/0)",
  script: "Script",
  language: "Language",
  length: "Length (ms)",
  asin: "ASIN",
  discsubtitle: "Disc subtitle",
  musicbrainz_recordingid: "MusicBrainz recording ID",
  musicbrainz_trackid: "MusicBrainz track ID",
  musicbrainz_albumid: "MusicBrainz release ID",
  musicbrainz_releasegroupid: "MusicBrainz release group ID",
  musicbrainz_artistid: "MusicBrainz artist ID",
  musicbrainz_albumartistid: "MusicBrainz album artist ID",
  youtube_video_id: "YouTube video ID",
};

const label = (name: string) => LABELS[name] ?? name;
const joined = (values: string[] | undefined) => (values ?? []).join("; ");
const split = (text: string) => text.split(";").map((v) => v.trim()).filter(Boolean);

interface Row {
  name: string;
  value: string;
}

/** Edit, add and remove the tags of a downloaded file. Multiple values go in one field, separated by ";". */
export function TagEditor({ trackId, fields, editable }: { trackId: string; fields: Record<string, string[]>; editable: string[] }) {
  const qc = useQueryClient();
  const initial = () => editable.filter((n) => n in fields).map((name) => ({ name, value: joined(fields[name]) }));
  const [rows, setRows] = useState<Row[]>(initial);

  // Only the tags that differ from the file: new values, or [] to remove.
  const changes: Record<string, string[]> = {};
  for (const name of editable) {
    const row = rows.find((r) => r.name === name);
    if (row ? row.value === joined(fields[name]) : !(name in fields)) continue;
    changes[name] = row ? split(row.value) : [];
  }
  const dirty = Object.keys(changes).length > 0;
  const missing = editable.filter((n) => !rows.some((r) => r.name === n));

  const save = useMutation({
    mutationFn: () => api.put<{ fields: Record<string, string[]> }>(`/api/track/${trackId}/tags`, { changes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["track", trackId] }),
  });

  const setValue = (name: string, value: string) => setRows((rs) => rs.map((r) => (r.name === name ? { ...r, value } : r)));
  const remove = (name: string) => setRows((rs) => rs.filter((r) => r.name !== name));
  const add = (name: string) => setRows((rs) => [...rs, { name, value: "" }]);

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty) save.mutate();
      }}
      data-testid="tag-editor"
    >
      <div className="space-y-1.5">
        {rows.length === 0 && <p className="text-sm text-muted-foreground">This file has no tags.</p>}
        {rows.map((r) => (
          <div key={r.name} className="grid grid-cols-[9.5rem_1fr_2rem] items-center gap-2 max-sm:grid-cols-[1fr_2rem] max-sm:gap-x-1 max-sm:gap-y-0.5">
            <label htmlFor={`tag-${r.name}`} className="truncate text-xs font-medium text-muted-foreground max-sm:col-span-2" title={r.name}>
              {label(r.name)}
            </label>
            <Input
              id={`tag-${r.name}`}
              value={r.value}
              onChange={(e) => setValue(r.name, e.target.value)}
              placeholder="Empty removes the tag"
              className="h-8 font-mono text-xs"
              data-tag={r.name}
            />
            <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={() => remove(r.name)} aria-label={`Remove ${label(r.name)}`} title="Remove tag">
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Separate multiple values with “;”. Retagging the album from MusicBrainz overwrites these edits.</p>
      {/* kept in view while scrolling through a long list of tags */}
      <div className="sticky -bottom-6 -mx-6 space-y-2 border-t bg-surface px-6 py-3 max-sm:-bottom-4 max-sm:-mx-4 max-sm:px-4">
        {save.error && <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">{save.error.message}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" size="sm" disabled={!dirty || save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save tags
          </Button>
          <Button type="button" size="sm" variant="ghost" disabled={!dirty || save.isPending} onClick={() => setRows(initial())}>
            <Undo2 /> Discard changes
          </Button>
          <div className="flex-1" />
          {missing.length > 0 && (
            <Select value="" onValueChange={add}>
              <SelectTrigger className="h-8 w-44 text-xs" aria-label="Add a tag">
                <SelectValue placeholder="Add a tag…" />
              </SelectTrigger>
              <SelectContent>
                {missing.map((n) => (
                  <SelectItem key={n} value={n} className="text-xs">
                    {label(n)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      </div>
    </form>
  );
}
