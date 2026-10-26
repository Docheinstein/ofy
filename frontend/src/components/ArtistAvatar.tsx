import { useState } from "react";
import { User } from "lucide-react";
import { artistImageUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Round artist photo (Wikidata/Commons, falling back to an album cover), or a placeholder icon.
 *  With `library`, the cover of their earliest album in the library instead, never fetched online. */
export function ArtistAvatar({ id, fallbackRg, wikidata, library, size = 250, className }: {
  id: string;
  fallbackRg?: string | null;
  wikidata?: string | null;
  library?: boolean;
  size?: 250 | 500 | 1200;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={cn("flex aspect-square items-center justify-center overflow-hidden rounded-full bg-elevated text-muted-foreground shadow-lg", className)}>
      {failed ? (
        <User className="h-1/3 w-1/3" />
      ) : (
        <img
          src={artistImageUrl(id, size, fallbackRg ?? undefined, wikidata ?? undefined, library)}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
