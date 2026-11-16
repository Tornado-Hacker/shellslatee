import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Wand2,
  Clock3,
  FileText,
  FolderOpen,
  Grid2x2,
  List,
  Search,
  SlidersHorizontal,
  Sparkles,
  Video,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { bridge } from "@/lib/bridge";
import { riseItem, stagger } from "@/lib/motion";
import { useStore } from "@/lib/store";
import type { SearchRow } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";
import { Badge, Button, Card, EmptyState, Input, SectionHeader, Select, Skeleton } from "@/components/ui";

type Sort = "order" | "title" | "duration";

export function LibraryPage() {
  const config = useStore((state) => state.config);
  const vault = useStore((state) => state.vault);
  const loading = useStore((state) => state.loadingVault);
  const notify = useStore((state) => state.notify);
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"fts" | "hybrid" | "semantic">("hybrid");
  const [results, setResults] = useState<SearchRow[]>([]);
  const [searching, setSearching] = useState(false);
  const [moduleFilter, setModuleFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [sort, setSort] = useState<Sort>("order");
  const [view, setView] = useState<"grid" | "list">("grid");

  const lessons = vault?.lessons ?? [];
  const modules = useMemo(() => Array.from(new Set(lessons.map((lesson) => lesson.module).filter(Boolean))).sort(), [lessons]);
  const tags = useMemo(() => Array.from(new Set(lessons.flatMap((lesson) => lesson.tags))).sort().slice(0, 20), [lessons]);

  useEffect(() => {
    if (!config?.vault || query.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      api
        .search(config.vault, query.trim(), mode)
        .then((data) => {
          if (!cancelled) setResults(data.rows);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, mode, config?.vault]);

  const visible = useMemo(() => {
    let rows = lessons.filter((lesson) => {
      if (moduleFilter && lesson.module !== moduleFilter) return false;
      if (tagFilter && !lesson.tags.includes(tagFilter)) return false;
      return true;
    });
    if (sort === "title") rows = [...rows].sort((a, b) => a.title.localeCompare(b.title));
    if (sort === "duration") rows = [...rows].sort((a, b) => b.duration - a.duration);
    return rows;
  }, [lessons, moduleFilter, tagFilter, sort]);

  const searching_now = query.trim().length >= 2;

  if (!vault) {
    return (
      <EmptyState
        icon={<FileText className="h-6 w-6" />}
        title={loading ? "Opening the vault…" : "No vault yet"}
        body={loading ? undefined : "Set a notes folder in Settings, or run the generator on a course folder first."}
        action={
          !loading ? (
            <div className="flex flex-wrap justify-center gap-2">
              <Button onClick={() => useStore.getState().setIngest(true)} icon={<Wand2 className="h-4 w-4" />}>Build from a folder</Button>
              <Button variant="outline" onClick={() => navigate("/settings")}>Open settings</Button>
            </div>
          ) : undefined
        }
      />
    );
  }

  return (
    <motion.div variants={stagger} initial="initial" animate="enter" className="space-y-6">
      <motion.div variants={riseItem}>
        <SectionHeader
          title={vault.title}
          subtitle={`${visible.length} lesson${visible.length === 1 ? "" : "s"} · ${formatDuration(vault.total_duration)} of lecture`}
          action={
            <Button
              variant="outline"
              size="sm"
              icon={<FolderOpen className="h-3.5 w-3.5" />}
              onClick={() => bridge.openPath(vault.out).catch(() => notify("Could not open folder", undefined, "error"))}
            >
              Open folder
            </Button>
          }
        />
      </motion.div>

      <motion.div variants={riseItem} className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search every note, concept and timestamp…"
              className="pl-9"
            />
          </div>
          <div className="flex gap-2">
            <Select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} className="w-[130px]">
              <option value="fts">Keyword</option>
              <option value="hybrid">Hybrid</option>
              <option value="semantic">Semantic</option>
            </Select>
            <Select value={sort} onChange={(event) => setSort(event.target.value as Sort)} className="w-[130px]">
              <option value="order">Course order</option>
              <option value="title">Title</option>
              <option value="duration">Longest</option>
            </Select>
            <div className="flex rounded-xl border p-0.5">
              <button
                onClick={() => setView("grid")}
                className={cn("rounded-lg p-1.5 transition", view === "grid" ? "bg-accent/15 text-accent" : "text-muted hover:text-ink")}
                aria-label="Grid view"
              >
                <Grid2x2 className="h-4 w-4" />
              </button>
              <button
                onClick={() => setView("list")}
                className={cn("rounded-lg p-1.5 transition", view === "list" ? "bg-accent/15 text-accent" : "text-muted hover:text-ink")}
                aria-label="List view"
              >
                <List className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {modules.length > 0 || tags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <SlidersHorizontal className="h-3.5 w-3.5 text-muted" />
            <Select value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)} className="h-8 w-auto py-0 text-xs">
              <option value="">All modules</option>
              {modules.map((module) => (
                <option key={module} value={module}>{module}</option>
              ))}
            </Select>
            <button onClick={() => setTagFilter("")} className={cn("chip", !tagFilter && "chip-accent")}>all tags</button>
            {tags.map((tag) => (
              <button
                key={tag}
                onClick={() => setTagFilter(tagFilter === tag ? "" : tag)}
                className={cn("chip", tagFilter === tag && "chip-accent")}
              >
                {tag}
              </button>
            ))}
          </div>
        ) : null}
      </motion.div>

      <AnimatePresence mode="wait">
        {searching_now ? (
          <motion.div key="search" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-2">
            <p className="text-[11px] uppercase tracking-wider text-muted">
              {searching ? "Searching…" : `${results.length} result${results.length === 1 ? "" : "s"} · ${mode}`}
            </p>
            {searching ? (
              <div className="space-y-2">{[0, 1, 2].map((index) => <Skeleton key={index} className="h-20 w-full" />)}</div>
            ) : results.length === 0 ? (
              <EmptyState title="No matches" body="Try a shorter phrase, or switch to keyword search." />
            ) : (
              results.map((row) => (
                <Link
                  key={`${row.path}-${row.section}-${row.snippet.slice(0, 12)}`}
                  to={`/note/${encodeURIComponent(row.path)}`}
                  className="card card-hover block p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold">{row.title}</p>
                    <Badge tone="muted">{row.section || "note"}</Badge>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-muted">{row.snippet}</p>
                </Link>
              ))
            )}
          </motion.div>
        ) : (
          <motion.div
            key="grid"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className={cn(view === "grid" ? "grid gap-3 sm:grid-cols-2 xl:grid-cols-3" : "flex flex-col gap-2")}
          >
            {visible.map((lesson) => (
              <motion.div key={lesson.rel} layout>
                <Link
                  to={`/note/${encodeURIComponent(lesson.rel)}`}
                  className={cn(
                    "card card-hover group block",
                    view === "grid" ? "h-full p-4" : "flex items-center gap-4 p-3.5",
                  )}
                >
                  <div className={cn("min-w-0", view === "grid" ? "" : "flex-1")}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="line-clamp-2 text-[13px] font-semibold leading-snug group-hover:text-accent">
                        {lesson.title}
                      </p>
                      {view === "grid" ? (
                        lesson.video ? <Video className="mt-0.5 h-3.5 w-3.5 shrink-0 text-iris" /> : <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
                      ) : null}
                    </div>
                    <p className={cn("mt-1 text-[11px] leading-snug text-muted", view === "grid" ? "line-clamp-2" : "line-clamp-1")}>
                      {lesson.summary}
                    </p>
                    <div className={cn("flex flex-wrap items-center gap-1.5", view === "grid" ? "mt-3" : "mt-1.5")}>
                      <Badge tone="muted"><Clock3 className="h-3 w-3" />{formatDuration(lesson.duration)}</Badge>
                      {lesson.module ? <Badge tone="muted">{lesson.module}</Badge> : null}
                      <Badge tone="iris"><Sparkles className="h-3 w-3" />{lesson.concepts.length}</Badge>
                    </div>
                  </div>
                  {view === "list" ? (
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-accent" />
                  ) : null}
                </Link>
              </motion.div>
            ))}
            {visible.length === 0 ? (
              <div className="col-span-full">
                <EmptyState title="Nothing on this shelf" body="Clear the filters or generate notes for this course." />
              </div>
            ) : null}
          </motion.div>
        )}
      </AnimatePresence>

      <Card className="flex items-center justify-between gap-4 p-4">
        <div>
          <p className="text-[13px] font-medium">Notes are plain Markdown</p>
          <p className="mt-0.5 text-[11px] text-muted">Open the folder in Obsidian, VS Code, or anything else. No lock-in.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => bridge.openPath(vault.out)} icon={<FolderOpen className="h-3.5 w-3.5" />}>
          Vault
        </Button>
      </Card>
    </motion.div>
  );
}
