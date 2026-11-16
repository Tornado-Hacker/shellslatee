import { AnimatePresence, motion } from "framer-motion";
import { Command, Menu, Moon, Plus, Search, Sun, Wand2, Wifi, WifiOff } from "lucide-react";
import { useLocation } from "react-router-dom";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Button } from "./ui/primitives";

const titles: Record<string, { title: string; sub: string }> = {
  "/": { title: "Home", sub: "Your study cockpit" },
  "/library": { title: "Library", sub: "Every lesson, one shelf" },
  "/study": { title: "Study", sub: "Active recall, spaced right" },
  "/ask": { title: "Ask", sub: "Answers with citations" },
  "/graph": { title: "Concept graph", sub: "How the course connects" },
  "/settings": { title: "Settings", sub: "Provider, keys, appearance" },
};

function current(pathname: string) {
  if (pathname.startsWith("/note")) return { title: "Lesson", sub: "Read, listen, recall" };
  return titles[pathname] ?? { title: "Shellslatee", sub: "" };
}

export function TopBar({
  onMenu,
  onCapture,
}: {
  onMenu: () => void;
  onCapture: () => void;
}) {
  const { pathname } = useLocation();
  const meta = current(pathname);
  const config = useStore((state) => state.config);
  const backend = useStore((state) => state.backend);
  const update = useStore((state) => state.update);
  const setPalette = useStore((state) => state.setPalette);
  const setIngest = useStore((state) => state.setIngest);

  const toggleTheme = () => update({ theme: config?.theme === "dark" ? "light" : "dark" });

  return (
    <header className="glass sticky top-0 z-30 flex h-16 items-center gap-3 border-b px-5">
      <button onClick={onMenu} className="btn-ghost rounded-lg p-2 lg:hidden" aria-label="Menu">
        <Menu className="h-5 w-5" />
      </button>

      <div className="min-w-0 flex-1">
        <AnimatePresence mode="wait">
          <motion.div
            key={meta.title}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18 }}
          >
            <h1 className="truncate text-[15px] font-semibold tracking-tight">{meta.title}</h1>
            <p className="truncate text-[11px] text-muted">{meta.sub}</p>
          </motion.div>
        </AnimatePresence>
      </div>

      <button
        onClick={() => setPalette(true)}
        className="hidden items-center gap-2 rounded-xl border bg-bg/60 px-3 py-2 text-xs text-muted transition hover:border-accent/30 hover:text-ink md:flex"
      >
        <Search className="h-3.5 w-3.5" />
        <span>Search notes, concepts…</span>
        <span className="ml-6 flex items-center gap-1">
          <Command className="h-3 w-3" />K
        </span>
      </button>

      <div
        className={cn(
          "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] sm:flex",
          backend.ready ? "border-good/30 bg-good/10 text-good" : "border-warn/30 bg-warn/10 text-warn",
        )}
        title={backend.ready ? `Engine ${backend.version ?? ""} on ${backend.base}` : backend.error ?? "Engine offline"}
      >
        {backend.ready ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
        {backend.ready ? "Local engine" : "Offline"}
      </div>

      <Button variant="outline" size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={onCapture} className="hidden sm:inline-flex">
        Capture
      </Button>

      <Button variant="ghost" size="sm" icon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => setIngest(true)} className="hidden md:inline-flex" title="Build the vault from a course folder">
        Build
      </Button>

      <button
        onClick={toggleTheme}
        className="relative rounded-lg p-2 text-muted transition hover:bg-ink/5 hover:text-ink"
        aria-label="Toggle theme"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={config?.theme}
            initial={{ rotate: -90, opacity: 0, scale: 0.6 }}
            animate={{ rotate: 0, opacity: 1, scale: 1 }}
            exit={{ rotate: 90, opacity: 0, scale: 0.6 }}
            transition={{ duration: 0.18 }}
            className="block"
          >
            {config?.theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </motion.span>
        </AnimatePresence>
      </button>
    </header>
  );
}
