import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type ImportResult } from "./api";
import { setLive } from "./live";

export function useTrackActions(releaseId?: string) {
  const qc = useQueryClient();
  const refresh = () => {
    if (releaseId) qc.invalidateQueries({ queryKey: ["release", releaseId] });
    qc.invalidateQueries({ queryKey: ["downloads"] });
    qc.invalidateQueries({ queryKey: ["track"] });
    qc.invalidateQueries({ queryKey: ["library"] });
  };
  const download = useMutation({
    mutationFn: ({ releaseId: rid, trackId }: { releaseId: string; trackId: string }) =>
      api.post(`/api/release/${rid}/tracks/${trackId}/download`),
    onMutate: ({ trackId }) => setLive(trackId, { status: "queued", progress: 0, stage: null }),
    onSettled: refresh,
  });
  const downloadAlbum = useMutation({
    mutationFn: (rid: string) => api.post(`/api/release/${rid}/download`),
    onSettled: refresh,
  });
  const retry = useMutation({
    mutationFn: (trackId: string) => api.post(`/api/track/${trackId}/retry`),
    onMutate: (trackId) => setLive(trackId, { status: "queued", progress: 0, stage: null, error: null }),
    onSettled: refresh,
  });
  const choose = useMutation({
    mutationFn: ({ trackId, videoId }: { trackId: string; videoId: string }) =>
      api.post(`/api/track/${trackId}/match`, { video_id: videoId }),
    onSettled: refresh,
  });
  const lyrics = useMutation({
    mutationFn: (trackId: string) => api.post(`/api/track/${trackId}/lyrics`),
    onSettled: refresh,
  });
  const albumLyrics = useMutation({
    mutationFn: (rid: string) => api.post(`/api/release/${rid}/lyrics`),
    onSettled: refresh,
  });
  const retag = useMutation({
    mutationFn: (rid: string) => api.post(`/api/release/${rid}/retag`),
    onSettled: refresh,
  });
  const importFiles = useMutation({
    mutationFn: (rid: string) => api.post<ImportResult>(`/api/release/${rid}/import-files`),
    onSettled: refresh,
  });
  return { download, downloadAlbum, retry, choose, lyrics, albumLyrics, retag, importFiles };
}
