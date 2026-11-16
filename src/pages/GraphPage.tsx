import { motion } from "framer-motion";
import { Compass, GitBranch, Search, Sparkles, Waypoints } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, Button, Card, EmptyState, Input, SectionHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { GraphEdge, GraphNode, GraphPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

type Positioned = GraphNode & { x: number; y: number; degree: number };

const WIDTH = 1200;
const HEIGHT = 800;

function layout(payload: GraphPayload): Positioned[] {
  const nodes: Positioned[] = payload.nodes.map((node, index) => {
    const angle = (index / Math.max(1, payload.nodes.length)) * Math.PI * 2;
    const radius = Math.min(WIDTH, HEIGHT) * 0.34 * (0.55 + ((index * 37) % 100) / 160);
    return { ...node, x: WIDTH / 2 + Math.cos(angle) * radius, y: HEIGHT / 2 + Math.sin(angle) * radius, degree: 0 };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edges = payload.edges.filter((edge) => byId.has(edge.src) && byId.has(edge.dst));
  for (const edge of edges) {
    byId.get(edge.src)!.degree += 1;
    byId.get(edge.dst)!.degree += 1;
  }

  const iterations = nodes.length > 260 ? 120 : 260;
  const area = WIDTH * HEIGHT;
  const k = Math.sqrt(area / Math.max(1, nodes.length)) * 0.42;

  for (let step = 0; step < iterations; step++) {
    const temperature = Math.max(0.6, (1 - step / iterations) * 26);
    const fx = new Map<string, number>();
    const fy = new Map<string, number>();
    for (const node of nodes) {
      fx.set(node.id, 0);
      fy.set(node.id, 0);
    }

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let distance = Math.hypot(dx, dy);
        if (distance < 0.01) {
          dx = (Math.random() - 0.5) * 0.4;
          dy = (Math.random() - 0.5) * 0.4;
          distance = 0.4;
        }
        const force = (k * k) / distance;
        const ux = (dx / distance) * force;
        const uy = (dy / distance) * force;
        fx.set(a.id, fx.get(a.id)! + ux);
        fy.set(a.id, fy.get(a.id)! + uy);
        fx.set(b.id, fx.get(b.id)! - ux);
        fy.set(b.id, fy.get(b.id)! - uy);
      }
    }

    for (const edge of edges) {
      const a = byId.get(edge.src)!;
      const b = byId.get(edge.dst)!;
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let distance = Math.hypot(dx, dy) || 0.4;
      const force = (distance * distance) / k;
      const ux = (dx / distance) * force * 0.55;
      const uy = (dy / distance) * force * 0.55;
      fx.set(a.id, fx.get(a.id)! - ux);
      fy.set(a.id, fy.get(a.id)! - uy);
      fx.set(b.id, fx.get(b.id)! + ux);
      fy.set(b.id, fy.get(b.id)! + uy);
    }

    for (const node of nodes) {
      const dx = node.x - WIDTH / 2;
      const dy = node.y - HEIGHT / 2;
      fx.set(node.id, fx.get(node.id)! - dx * 0.012);
      fy.set(node.id, fy.get(node.id)! - dy * 0.012);
      const magnitude = Math.hypot(fx.get(node.id)!, fy.get(node.id)!) || 1;
      const cap = Math.min(magnitude, temperature);
      node.x += (fx.get(node.id)! / magnitude) * cap;
      node.y += (fy.get(node.id)! / magnitude) * cap;
      node.x = Math.max(30, Math.min(WIDTH - 30, node.x));
      node.y = Math.max(30, Math.min(HEIGHT - 30, node.y));
    }
  }

  for (const node of nodes) {
    node.degree = byId.get(node.id)?.degree ?? 0;
  }
  return nodes;
}

export function GraphPage() {
  const config = useStore((state) => state.config);
  const notify = useStore((state) => state.notify);
  const navigate = useNavigate();
  const [data, setData] = useState<GraphPayload | null>(null);
  const [semantic, setSemantic] = useState(false);
  const [query, setQuery] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    if (!config?.vault) return;
    let cancelled = false;
    setData(null);
    api
      .graph(config.vault, semantic)
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => notify("Could not build graph", err instanceof Error ? err.message : String(err), "error"));
    return () => {
      cancelled = true;
    };
  }, [config?.vault, semantic, notify]);

  const nodes = useMemo(() => (data ? layout(data) : []), [data]);
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const edges = useMemo<GraphEdge[]>(() => (data ? data.edges.filter((edge) => byId.has(edge.src) && byId.has(edge.dst)) : []), [data, byId]);
  const match = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return null;
    return new Set(nodes.filter((node) => node.label.toLowerCase().includes(needle)).map((node) => node.id));
  }, [nodes, query]);

  const focus = selected ?? hover;
  const neighbors = useMemo(() => {
    if (!focus) return null;
    const set = new Set<string>([focus]);
    for (const edge of edges) {
      if (edge.src === focus) set.add(edge.dst);
      if (edge.dst === focus) set.add(edge.src);
    }
    return set;
  }, [focus, edges]);

  if (!config?.vault) {
    return (
      <EmptyState
        icon={<Waypoints className="h-6 w-6" />}
        title="No vault, no map"
        body="Once a vault is open, every lesson and concept links into one graph."
        action={<Link to="/settings" className="btn btn-primary btn-sm">Open settings</Link>}
      />
    );
  }

  if (!data) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-52" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    );
  }

  const picked = selected ? byId.get(selected) : null;

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      <SectionHeader
        title="The map"
        subtitle={`${data.counts.lessons ?? nodes.filter((node) => node.kind === "lesson").length} lessons · ${data.counts.concepts ?? nodes.filter((node) => node.kind === "concept").length} concepts · ${edges.length} links`}
        action={
          <Button variant={semantic ? "primary" : "outline"} size="sm" onClick={() => setSemantic((prev) => !prev)} icon={<Sparkles className="h-3.5 w-3.5" />}>
            {semantic ? "Semantic links on" : "Add semantic links"}
          </Button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="relative overflow-hidden p-0">
          <div className="absolute left-3 top-3 z-10 w-56">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a concept…" className="h-8 bg-surface/90 pl-8 text-[12px] backdrop-blur" />
            </div>
          </div>
          <div className="absolute bottom-3 left-3 z-10 flex items-center gap-2 rounded-xl border bg-surface/85 px-2.5 py-1.5 text-[10px] backdrop-blur">
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-accent" />lesson</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-iris" />concept</span>
          </div>
          <div className="absolute bottom-3 right-3 z-10 flex gap-1">
            {[0.7, 1, 1.35].map((value) => (
              <button key={value} onClick={() => setZoom(value)} className={cn("rounded-lg border bg-surface/85 px-2 py-1 text-[10px] backdrop-blur", zoom === value && "border-accent/50 text-accent")}>
                {Math.round(value * 100)}%
              </button>
            ))}
          </div>

          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-[560px] w-full touch-none select-none bg-[radial-gradient(circle_at_50%_40%,rgb(var(--accent)/0.06),transparent_60%)]">
            <defs>
              <linearGradient id="edge" x1="0" x2="1">
                <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity="0.35" />
                <stop offset="100%" stopColor="rgb(var(--iris))" stopOpacity="0.35" />
              </linearGradient>
            </defs>
            <g transform={`translate(${(WIDTH * (1 - zoom)) / 2} ${(HEIGHT * (1 - zoom)) / 2}) scale(${zoom})`}>
              {edges.map((edge, index) => {
                const a = byId.get(edge.src)!;
                const b = byId.get(edge.dst)!;
                const dim = neighbors ? !(neighbors.has(edge.src) && neighbors.has(edge.dst)) : false;
                return (
                  <line
                    key={`${edge.src}-${edge.dst}-${edge.rel}-${index}`}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke={edge.rel === "related" ? "url(#edge)" : "rgb(var(--line))"}
                    strokeWidth={neighbors && !dim ? 1.6 : 0.8}
                    opacity={dim ? 0.12 : edge.rel === "related" ? 0.55 : 0.8}
                  />
                );
              })}
              {nodes.map((node) => {
                const active = focus === node.id;
                const dim = (neighbors && !neighbors.has(node.id)) || (match && !match.has(node.id));
                const radius = node.kind === "lesson" ? 7 : 4.5 + Math.min(3, node.degree * 0.35);
                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x} ${node.y})`}
                    opacity={dim ? 0.18 : 1}
                    className="cursor-pointer"
                    onMouseEnter={() => setHover(node.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => {
                      setSelected(node.id);
                      if (node.kind === "lesson" && node.rel) navigate(`/note/${encodeURIComponent(node.rel)}`);
                    }}
                  >
                    {active ? <circle r={radius + 7} fill="rgb(var(--accent))" opacity={0.18} /> : null}
                    <circle
                      r={radius}
                      fill={node.kind === "lesson" ? "rgb(var(--accent))" : "rgb(var(--iris))"}
                      stroke="rgb(var(--surface))"
                      strokeWidth={active ? 2 : 1}
                    />
                    {active || (match && match.has(node.id)) || node.degree >= 6 ? (
                      <text y={-radius - 6} textAnchor="middle" className="pointer-events-none text-[11px]" fill="rgb(var(--ink))" style={{ fontSize: 11 }}>
                        {node.label.length > 34 ? `${node.label.slice(0, 32)}…` : node.label}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>
          </svg>
        </Card>

        <div className="space-y-3">
          {picked ? (
            <Card className="space-y-3 p-4">
              <Badge tone={picked.kind === "lesson" ? "accent" : "iris"}>{picked.kind}</Badge>
              <p className="font-display text-lg leading-snug">{picked.label}</p>
              {picked.module ? <p className="text-[11px] text-muted">{picked.module}</p> : null}
              <p className="text-[11px] text-muted">{picked.degree} connection{picked.degree === 1 ? "" : "s"}</p>
              {picked.kind === "lesson" && picked.rel ? (
                <Button size="sm" className="w-full" onClick={() => navigate(`/note/${encodeURIComponent(picked.rel!)}`)} icon={<Compass className="h-3.5 w-3.5" />}>
                  Open lesson
                </Button>
              ) : (
                <Link to={`/library`} className="btn btn-outline btn-sm w-full">Find in library</Link>
              )}
            </Card>
          ) : (
            <Card className="space-y-2 p-4">
              <div className="flex items-center gap-2 text-[12px] font-medium"><GitBranch className="h-3.5 w-3.5 text-accent" />How to read it</div>
              <p className="text-[11px] leading-relaxed text-muted">Warm dots are lessons, violet dots are concepts. Lines mean “this lesson covers this concept” — semantic links add inferred relations between lessons.</p>
              <p className="text-[11px] leading-relaxed text-muted">Hover to isolate a neighbourhood. Click any node to inspect it.</p>
            </Card>
          )}

          <Card className="space-y-2 p-4">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Most connected</p>
            {[...nodes]
              .sort((a, b) => b.degree - a.degree)
              .slice(0, 8)
              .map((node) => (
                <button
                  key={node.id}
                  onClick={() => {
                    setSelected(node.id);
                    setHover(node.id);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left text-[11px] transition hover:bg-surface"
                >
                  <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", node.kind === "lesson" ? "bg-accent" : "bg-iris")} />
                  <span className="flex-1 truncate">{node.label}</span>
                  <span className="text-muted">{node.degree}</span>
                </button>
              ))}
          </Card>
        </div>
      </div>
    </motion.div>
  );
}
