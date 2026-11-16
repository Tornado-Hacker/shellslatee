import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  BookOpen,
  Brain,
  GitBranch,
  Home,
  MessagesSquare,
  Moon,
  Palette,
  Plus,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";
import { cn, fuzzyScore } from "@/lib/utils";

type Item = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  run: () => void;
};

export function CommandPalette({ onCapture }: { onCapture: () => void }) {
  const open = useStore((state) => state.paletteOpen);
  const setPalette = useStore((state) => state.setPalette);
  const vault = useStore((state) => state.vault);
  const config = useStore((state) => state.config);
  const update = useStore((state) => state.update);
  const notify = useStore((state) => state.notify);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const close = () => {
    setPalette(false);
    setQuery("");
    setActive(0);
  };

  const go = (to: string) => {
    navigate(to);
    close();
  };

  const items = useMemo<Item[]>(() => {
    const base: Item[] = [
      { id: "nav-home", group: "Go", label: "Home", icon: Home, run: () => go("/") },
      { id: "nav-library", group: "Go", label: "Library", icon: BookOpen, run: () => go("/library") },
      { id: "nav-study", group: "Go", label: "Study", icon: Brain, run: () => go("/study") },
      { id: "nav-ask", group: "Go", label: "Ask the course", icon: MessagesSquare, run: () => go("/ask") },
      { id: "nav-graph", group: "Go", label: "Concept graph", icon: GitBranch, run: () => go("/graph") },
      { id: "nav-settings", group: "Go", label: "Settings", icon: Settings, run: () => go("/settings") },
      {
        id: "act-capture",
        group: "Do",
        label: "Quick capture a thought",
        hint: "inbox",
        icon: Plus,
        run: () => {
          close();
          onCapture();
        },
      },
      {
        id: "act-theme",
        group: "Do",
        label: `Switch to ${config?.theme === "dark" ? "light" : "dark"} theme`,
        icon: Moon,
        run: () => {
          update({ theme: config?.theme === "dark" ? "light" : "dark" });
          notify("Theme switched", undefined, "success");
          close();
        },
      },
      {
        id: "act-accent",
        group: "Do",
        label: "Cycle accent color",
        icon: Palette,
        run: () => {
          const order = ["ember", "iris", "jade", "cobalt"] as const;
          const next = order[(order.indexOf(config?.accent ?? "ember") + 1) % order.length];
          update({ accent: next });
          close();
        },
      },
      {
        id: "act-study",
        group: "Do",
        label: "Start a recall session",
        hint: "cards due today",
        icon: Sparkles,
        run: () => go("/study"),
      },
    ];

    const lessons: Item[] = (vault?.lessons ?? []).map((lesson) => ({
      id: `lesson-${lesson.rel}`,
      group: "Lessons",
      label: lesson.title,
      hint: lesson.module || undefined,
      icon: BookOpen,
      run: () => go(`/note/${encodeURIComponent(lesson.rel)}`),
    }));

    const concepts: Item[] = (vault?.concepts ?? []).slice(0, 80).map((concept) => ({
      id: `concept-${concept.slug}`,
      group: "Concepts",
      label: concept.name,
      hint: `${concept.lessons.length} lesson${concept.lessons.length === 1 ? "" : "s"}`,
      icon: Sparkles,
      run: () => {
        if (concept.lessons[0]) go(`/note/${encodeURIComponent(concept.lessons[0])}`);
      },
    }));

    return [...base, ...lessons, ...concepts];
  }, [vault, config, navigate, onCapture, update, notify, setPalette]);

  const filtered = useMemo(() => {
    const scored = items
      .map((item) => ({ item, score: fuzzyScore(query, `${item.label} ${item.group} ${item.hint ?? ""}`) }))
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score);
    return scored.slice(0, 40).map((entry) => entry.item);
  }, [items, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      window.setTimeout(() => inputRef.current?.focus(), 40);
    }
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((value) => Math.min(filtered.length - 1, value + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((value) => Math.max(0, value - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      filtered[active]?.run();
    } else if (event.key === "Escape") {
      close();
    }
  };

  let lastGroup = "";

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[85] flex justify-center px-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={close} />
          <motion.div
            initial={{ opacity: 0, y: -14, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.99 }}
            transition={{ type: "spring", stiffness: 380, damping: 34 }}
            className="relative h-fit w-full max-w-2xl overflow-hidden rounded-xl3 border bg-surface shadow-lift"
          >
            <div className="flex items-center gap-3 border-b px-4">
              <Search className="h-4 w-4 text-muted" />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Search lessons, concepts, actions…"
                className="h-14 flex-1 bg-transparent text-sm outline-none placeholder:text-muted/70"
              />
              <span className="kbd">esc</span>
            </div>
            <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-2">
              {filtered.length === 0 ? (
                <p className="px-3 py-8 text-center text-sm text-muted">Nothing matches “{query}”.</p>
              ) : (
                filtered.map((item, index) => {
                  const showGroup = item.group !== lastGroup;
                  lastGroup = item.group;
                  return (
                    <div key={item.id}>
                      {showGroup ? (
                        <p className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted">
                          {item.group}
                        </p>
                      ) : null}
                      <button
                        data-index={index}
                        onMouseEnter={() => setActive(index)}
                        onClick={() => item.run()}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition",
                          index === active ? "bg-accent/12 text-ink" : "text-muted hover:bg-ink/5",
                        )}
                      >
                        <item.icon className={cn("h-4 w-4", index === active ? "text-accent" : "text-muted")} />
                        <span className="flex-1 truncate">{item.label}</span>
                        {item.hint ? <span className="truncate text-[11px] text-muted">{item.hint}</span> : null}
                        <ArrowRight className={cn("h-3.5 w-3.5", index === active ? "opacity-100" : "opacity-0")} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
            <div className="flex items-center gap-4 border-t px-4 py-2.5 text-[11px] text-muted">
              <span className="flex items-center gap-1"><span className="kbd">↑</span><span className="kbd">↓</span> navigate</span>
              <span className="flex items-center gap-1"><span className="kbd">↵</span> open</span>
              <span className="ml-auto">{filtered.length} results</span>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
