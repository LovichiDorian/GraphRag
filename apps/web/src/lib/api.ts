import type { EntityDetails, GraphData, Profile, Stats } from "./types";

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { accept: "application/json", ...init?.headers } });
  if (!response.ok) throw new Error(`${path} → ${response.status}`);
  return (await response.json()) as T;
}

export const api = {
  graph: () => getJson<GraphData>("/api/graph"),
  profile: () => getJson<Profile>("/api/profile"),
  stats: () => getJson<Stats>("/api/stats"),
  node: (id: string) => getJson<EntityDetails>(`/api/graph/node/${encodeURIComponent(id)}`),
  search: (q: string) =>
    getJson<{ results: { id: string; name: string; type: string }[] }>(
      `/api/graph/search?q=${encodeURIComponent(q)}`,
    ),
};
