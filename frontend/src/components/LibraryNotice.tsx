import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

interface LibraryStatus {
  available: boolean;
  path: string;
}

/** A strip asking to attach the drive while the library folder is missing; the library keeps what it knew
 * meanwhile. Checked now and then, and rescanned once the folder is back. */
export function LibraryNotice() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["library", "status"],
    queryFn: () => api.get<LibraryStatus>("/api/library/status"),
    refetchInterval: (q) => (q.state.data?.available === false ? 5000 : 60000),
  });
  const wasMissing = useRef(false);
  useEffect(() => {
    if (!data) return;
    if (data.available && wasMissing.current) {
      api.post("/api/library/rescan").then(() => qc.invalidateQueries(), () => {});
    }
    wasMissing.current = !data.available;
  }, [data, qc]);
  if (!data || data.available) return null;
  return (
    <div role="status" className="flex items-center gap-2 rounded-lg bg-warning/15 px-4 py-2 text-sm text-warning max-md:rounded-none">
      <HardDrive className="h-4 w-4 shrink-0" />
      <span className="min-w-0">
        Library not found at <span className="break-all font-medium">{data.path}</span>. Attach the drive to play your music.
      </span>
    </div>
  );
}
