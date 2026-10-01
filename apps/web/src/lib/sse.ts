/** Minimal reader for Vercel AI SDK UI-message streams (SSE `data: {json}` frames). */
export type UIChunk = { type: string; [key: string]: unknown };

export async function* readUIStream(response: Response): AsyncGenerator<UIChunk> {
  if (!response.body) return;
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6);
        if (payload === "[DONE]") return;
        yield JSON.parse(payload) as UIChunk;
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // not JSON
  }
  return response.status === 429
    ? "Too many requests — please wait a moment."
    : `Request failed (${response.status}).`;
}
