import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { api, artistImageUrl, type ArtistDetail } from "@/lib/api";
import { AlbumCard } from "@/components/AlbumCard";
import { ArtistAvatar } from "@/components/ArtistAvatar";
import { Button } from "@/components/ui/button";
import { SyncToggle } from "@/components/SyncToggle";
import { FloatingBack } from "@/components/Sidebar";

export function ArtistPage() {
  const { id } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["artist", id],
    queryFn: () => api.get<ArtistDetail>(`/api/artist/${id}`),
  });
  if (isLoading) return <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin" /></div>;
  if (error || !data) return <div className="p-8 text-destructive">{(error as Error)?.message}</div>;
  const years = [data.life_span?.begin?.slice(0, 4), data.life_span?.end?.slice(0, 4)].filter(Boolean).join("–");

  return (
    <div>
      <FloatingBack />
      <header className="relative flex h-72 items-end gap-6 overflow-hidden bg-gradient-to-b from-neutral-600/60 to-surface p-6 max-md:h-auto max-md:flex-col max-md:items-center max-md:gap-4 max-md:px-4 max-md:pb-4 max-md:pt-14 max-md:text-center">
        <img
          src={artistImageUrl(data.id, 500, data.image_release_group ?? undefined, data.wikidata_id ?? undefined)}
          alt=""
          className="absolute inset-0 h-full w-full scale-110 object-cover opacity-30 blur-2xl"
          onError={(e) => (e.currentTarget.style.display = "none")}
        />
        <ArtistAvatar id={data.id} fallbackRg={data.image_release_group} wikidata={data.wikidata_id} size={500} className="relative w-44 shrink-0 shadow-2xl max-md:w-40" />
        <div className="relative min-w-0 max-md:w-full">
          <p className="text-sm font-semibold max-md:hidden">{data.type ?? "Artist"}</p>
          <h1 className="truncate text-5xl font-black tracking-tight max-md:line-clamp-2 max-md:whitespace-normal max-md:break-words max-md:text-4xl md:text-7xl" data-testid="artist-name">{data.name}</h1>
          <p className="mt-3 text-sm text-muted-foreground max-md:mt-2">
            {[data.country, years, data.disambiguation, data.genres.slice(0, 3).join(", ")].filter(Boolean).join(" · ")}
          </p>
          <SyncToggle variant="button" className="mt-4" target={{ kind: "artist", id: data.id, title: data.name, subtitle: "Artist" }} />
        </div>
      </header>

      <div className="space-y-10 p-6 max-md:space-y-8 max-md:px-3 max-md:py-4">
        {data.discography.map((bucket) => <Bucket key={bucket.type} bucket={bucket} />)}

        {data.related.length > 0 && (
          <section>
            <h2 className="mb-3 text-2xl font-bold max-md:px-1 max-md:text-xl">Related artists</h2>
            <div className="flex flex-wrap gap-2">
              {data.related.map((r) => (
                <Link key={r.id} to={`/artist/${r.id}`} className="flex items-center gap-2 rounded-full bg-elevated py-1 pl-1 pr-4 text-sm hover:bg-accent">
                  <ArtistAvatar id={r.id} className="w-7 shadow-none" />
                  <span className="font-semibold">{r.name}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{r.relation}</span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function Bucket({ bucket }: { bucket: ArtistDetail["discography"][number] }) {
  const [all, setAll] = useState(false);
  const items = all ? bucket.items : bucket.items.slice(0, 12);
  return (
    <section data-testid={`bucket-${bucket.type}`}>
      <div className="mb-2 flex items-end justify-between max-md:px-1">
        <h2 className="text-2xl font-bold max-md:text-xl">{bucket.type === "Album" ? "Albums" : bucket.type === "Single/EP" ? "Singles & EPs" : bucket.type === "Compilation" ? "Compilations" : bucket.type}</h2>
        {bucket.items.length > 12 && (
          <Button variant="link" className="text-muted-foreground" onClick={() => setAll(!all)}>
            {all ? "Show less" : `Show all ${bucket.items.length}`}
          </Button>
        )}
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-1 max-md:grid-cols-2">
        {items.map((rg) => <AlbumCard key={rg.id} rg={rg} subtitle={[rg.year, rg.primary_type].filter(Boolean).join(" • ")} />)}
      </div>
    </section>
  );
}
