import { ImageResponse } from "next/og";

export const alt = "Dorian Lovichi — Don't read my CV. Query it.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const NODES = [
  [180, 140, 10, "#a78bfa"],
  [320, 220, 7, "#22d3ee"],
  [250, 380, 9, "#34d399"],
  [420, 120, 6, "#fbbf24"],
  [520, 300, 12, "#f8fafc"],
  [640, 170, 7, "#e879f9"],
  [700, 420, 8, "#38bdf8"],
  [380, 500, 6, "#fb923c"],
  [820, 260, 9, "#22d3ee"],
  [960, 140, 6, "#a78bfa"],
  [1040, 360, 8, "#34d399"],
  [900, 500, 7, "#fbbf24"],
] as const;
const EDGES = [
  [0, 1],
  [1, 4],
  [2, 4],
  [3, 4],
  [4, 5],
  [4, 6],
  [6, 7],
  [5, 8],
  [8, 9],
  [8, 10],
  [10, 11],
  [6, 11],
  [1, 2],
] as const;

export default function OpengraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        position: "relative",
        background: "#04050a",
        color: "white",
      }}
    >
      <svg width="1200" height="630" style={{ position: "absolute", inset: 0, opacity: 0.55 }}>
        {EDGES.map(([a, b]) => (
          <line
            key={`${a}-${b}`}
            x1={NODES[a]![0]}
            y1={NODES[a]![1]}
            x2={NODES[b]![0]}
            y2={NODES[b]![1]}
            stroke="#475569"
            strokeWidth="2"
          />
        ))}
        {NODES.map(([x, y, r, c]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={r * 1.6} fill={c} />
        ))}
      </svg>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          padding: "64px 72px",
          width: "100%",
          background: "linear-gradient(180deg, rgba(4,5,10,0) 20%, rgba(4,5,10,0.95) 75%)",
        }}
      >
        <div style={{ fontSize: 26, color: "#a5b4fc", marginBottom: 14 }}>
          Dorian Lovichi · Full-Stack Engineer · Applied AI & DevOps
        </div>
        <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.05, letterSpacing: -2 }}>
          Don&apos;t read my CV.
        </div>
        <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.05, letterSpacing: -2, color: "#67e8f9" }}>
          Query it.
        </div>
        <div style={{ fontSize: 24, color: "#94a3b8", marginTop: 20 }}>
          Agentic GraphRAG · Gemini · Neo4j · Kubernetes — graphrag.dorianlovichi.com
        </div>
      </div>
    </div>,
    size,
  );
}
