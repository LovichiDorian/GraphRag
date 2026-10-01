"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import * as THREE from "three";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { isLandmark, nodeColor, nodeRadius } from "@/lib/graph-style";
import { useUI } from "@/lib/store";
import { type Theme, useTheme } from "@/lib/theme";
import type { GraphData, GraphLink, GraphNode } from "@/lib/types";
import { type GraphFocus, linkKey, useGraphFocus } from "./use-graph-focus";

interface Props {
  data: GraphData;
  width: number;
  height: number;
  onNodeClick: (node: GraphNode) => void;
}

type Visual = {
  group: THREE.Group;
  sphere: THREE.MeshStandardMaterial;
  halo: THREE.SpriteMaterial;
  label?: HTMLDivElement;
  landmark: boolean;
};

type Look = {
  background: string;
  bloom: boolean;
  blending: THREE.Blending;
  link: string;
  linkFocus: string;
  linkOpacity: number;
  particle: string;
  /** Material values for nodes that are emphasised / in the evidence subgraph / faded out. */
  emissive: [number, number, number];
  halo: [number, number, number];
  opacity: [number, number, number];
};

const LOOKS: Record<Theme, Look> = {
  // Glowing nodes on near-black, with bloom post-processing.
  dark: {
    background: "#04050a",
    bloom: true,
    blending: THREE.AdditiveBlending,
    link: "#3b4466",
    linkFocus: "#a5b4fc",
    linkOpacity: 0.45,
    particle: "#67e8f9",
    emissive: [1.1, 0.55, 0.08],
    halo: [0.55, 0.22, 0.02],
    opacity: [0.95, 0.95, 0.1],
  },
  // Glossy, saturated nodes on a transparent canvas (the page's dot grid shows through). Bloom on a
  // light background only washes colours out, so it is off.
  light: {
    background: "rgba(0,0,0,0)",
    bloom: false,
    blending: THREE.NormalBlending,
    link: "#a3b0c2",
    linkFocus: "#7c3aed",
    linkOpacity: 0.5,
    particle: "#0891b2",
    emissive: [0.45, 0.16, 0],
    halo: [0.4, 0.14, 0],
    opacity: [1, 0.96, 0.16],
  },
};

/** Applies the focus state (evidence subgraph) to one node's materials and label. */
function applyStyle(visual: Visual, id: string, focus: GraphFocus, look: Look) {
  const inFocus = !focus.active || focus.nodes.has(id);
  const emphasised = focus.emphasis.has(id);
  const level = emphasised ? 0 : inFocus ? 1 : 2;
  visual.sphere.opacity = look.opacity[level];
  visual.sphere.emissiveIntensity = look.emissive[level];
  visual.halo.opacity = look.halo[level];
  visual.group.scale.setScalar(emphasised ? 1.5 : focus.active && inFocus ? 1.15 : 1);
  if (visual.label) {
    const show = focus.active
      ? inFocus && (emphasised || focus.nodes.size <= 28 || visual.landmark)
      : visual.landmark;
    visual.label.style.opacity = show ? "1" : "0";
    visual.label.dataset.emphasis = emphasised ? "true" : "false";
  }
}

function haloTexture() {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,0.75)");
  gradient.addColorStop(0.3, "rgba(255,255,255,0.18)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

export default function Graph3D({ data, width, height, onNodeClick }: Props) {
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined);
  const visuals = useRef(new Map<string, Visual>());
  const fitted = useRef(false);
  const texture = useMemo(() => (typeof document === "undefined" ? null : haloTexture()), []);
  // HTML labels live in a CSS2D layer: crisp text that the bloom pass cannot blur.
  const labelRenderer = useMemo(() => (typeof window === "undefined" ? null : new CSS2DRenderer()), []);
  const extraRenderers = useMemo(() => (labelRenderer ? [labelRenderer] : []), [labelRenderer]);
  const maxRank = useMemo(
    () => Math.max(...data.nodes.filter((n) => n.type !== "Person").map((n) => n.pagerank), 1e-6),
    [data],
  );
  const focus = useGraphFocus(data);
  const theme = useTheme();
  const look = LOOKS[theme];
  const heroVisible = useUI((s) => !s.highlight && !s.selectedId);
  const shift = useRef(0);

  useEffect(() => {
    if (labelRenderer) labelRenderer.domElement.style.pointerEvents = "none";
  }, [labelRenderer]);

  // Nodes rebuilt by the library (e.g. after a theme switch) start in the current focus state.
  const focusRef = useRef(focus);
  useEffect(() => {
    focusRef.current = focus;
  }, [focus]);

  // Bloom post-processing, dark theme only (on a light background it just washes colours out).
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !look.bloom) return;
    const bloom = new UnrealBloomPass(new THREE.Vector2(width, height), 0.85, 0.45, 0.32);
    fg.postProcessingComposer().addPass(bloom);
    return () => {
      fg.postProcessingComposer().removePass(bloom);
      bloom.dispose();
    };
  }, [width, height, look.bloom]);

  // Gentle auto-rotation and layout forces, configured once.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const controls = fg.controls() as {
      autoRotate?: boolean;
      autoRotateSpeed?: number;
      enableDamping?: boolean;
    };
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.45;
    controls.enableDamping = true;
    fg.d3Force("charge")?.strength?.(-150);
    fg.d3Force("link")?.distance?.((link: GraphLink) => {
      const target = typeof link.target === "object" ? link.target : null;
      const source = typeof link.source === "object" ? link.source : null;
      if (source?.type === "Person") return 95;
      return target?.type === "Skill" ? 38 : 64;
    });
    // Frame the graph early, then again once the layout settles (see onEngineStop).
    const timers = [900, 2600].map((ms) =>
      window.setTimeout(() => !fitted.current && fg.zoomToFit(900, 10), ms),
    );
    return () => {
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, []);

  // While the hero copy covers the top-left corner of wide screens, slide the camera's view
  // window so the graph sits to its right; glide back when an answer takes the stage.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const camera = fg.camera() as THREE.PerspectiveCamera;
    const wide = window.matchMedia("(min-width: 1024px)").matches;
    const from = shift.current;
    const to = heroVisible && wide ? Math.round(width * 0.15) : 0;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min((now - start) / 700, 1);
      const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      shift.current = from + (to - from) * eased;
      if (shift.current === 0) camera.clearViewOffset();
      else camera.setViewOffset(width, height, -shift.current, 0, width, height);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [heroVisible, width, height]);

  // Restyle nodes in place whenever the evidence subgraph (or the theme) changes.
  useEffect(() => {
    for (const node of data.nodes) {
      const visual = visuals.current.get(node.id);
      if (visual) applyStyle(visual, node.id, focus, look);
    }
  }, [focus, look, data.nodes]);

  // Frame the evidence subgraph and pause the rotation while it is shown.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const controls = fg.controls() as { autoRotate?: boolean };
    controls.autoRotate = !focus.active;
    if (focus.active && focus.nodes.size > 0) {
      const timer = window.setTimeout(
        () => fg.zoomToFit(1400, 90, (n) => focus.nodes.has(String(n.id))),
        120,
      );
      return () => window.clearTimeout(timer);
    }
    if (!focus.active && fitted.current) fg.zoomToFit(1400, 40);
    return undefined;
  }, [focus]);

  // Stable accessors: a new function identity would make three-forcegraph rebuild every node.
  const nodeLabel = useCallback(
    (n: GraphNode) =>
      `<div class="scene-tooltip">${n.name}<br/><span style="opacity:.6">${n.type}</span></div>`,
    [],
  );
  const nodeObject = useCallback(
    (node: GraphNode) => {
      const color = new THREE.Color(nodeColor(node, theme));
      const radius = nodeRadius(node, maxRank) * 0.8;
      const group = new THREE.Group();
      const sphere = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.55,
        roughness: 0.4,
        metalness: 0.15,
        transparent: true,
        opacity: 0.95,
      });
      group.add(new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 18), sphere));
      const halo = new THREE.SpriteMaterial({
        map: texture,
        color,
        transparent: true,
        opacity: 0.22,
        depthWrite: false,
        blending: LOOKS[theme].blending,
      });
      const glow = new THREE.Sprite(halo);
      glow.scale.setScalar(radius * 3.6);
      group.add(glow);
      const landmark = isLandmark(node, maxRank);
      let label: HTMLDivElement | undefined;
      if (node.type !== "Skill" || node.pagerank / maxRank > 0.12) {
        label = document.createElement("div");
        label.className = `graph-label graph-label--${node.type.toLowerCase()}`;
        label.textContent = node.name.length > 30 ? `${node.name.slice(0, 28)}…` : node.name;
        label.style.opacity = landmark ? "1" : "0";
        const object = new CSS2DObject(label);
        object.position.set(0, radius + 3.5, 0);
        object.center.set(0.5, 1);
        group.add(object);
      }
      const visual = { group, sphere, halo, label, landmark };
      visuals.current.set(node.id, visual);
      applyStyle(visual, node.id, focusRef.current, LOOKS[theme]);
      if (node.type === "Person") {
        node.fx = 0;
        node.fy = 0;
        node.fz = 0;
      }
      return group;
    },
    [maxRank, texture, theme],
  );

  return (
    <ForceGraph3D<GraphNode, GraphLink>
      ref={fgRef}
      width={width}
      height={height}
      graphData={data}
      backgroundColor={look.background}
      controlType="orbit"
      showNavInfo={false}
      extraRenderers={extraRenderers as never}
      warmupTicks={90}
      cooldownTicks={260}
      onEngineStop={() => {
        if (!fitted.current) {
          fitted.current = true;
          fgRef.current?.zoomToFit(1200, 10);
        }
      }}
      nodeLabel={nodeLabel}
      nodeThreeObject={nodeObject}
      linkColor={(link) => (focus.links.has(linkKey(link)) ? look.linkFocus : look.link)}
      linkOpacity={look.linkOpacity}
      linkWidth={(link) => (focus.links.has(linkKey(link)) ? 1.2 : 0)}
      linkDirectionalParticles={(link) => (focus.links.has(linkKey(link)) ? 3 : 0)}
      linkDirectionalParticleWidth={1.6}
      linkDirectionalParticleSpeed={0.006}
      linkDirectionalParticleColor={() => look.particle}
      onNodeClick={(node) => onNodeClick(node)}
      onNodeHover={(node) => {
        document.body.style.cursor = node ? "pointer" : "default";
      }}
    />
  );
}
