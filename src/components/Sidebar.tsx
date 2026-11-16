import { motion } from "framer-motion";
import {
  BookOpen,
  Brain,
  Command,
  Flame,
  GitBranch,
  Home,
  MessagesSquare,
  Settings,
  Sparkles,
} from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { cn, todayKey } from "@/lib/utils";
import { useStore } from "@/lib/store";
import { ProgressRing } from "./ui/primitives";

const nav = [
  { to: "/", label: "Home", icon: Home },
  { to: "/library", label: "Library", icon: BookOpen },
  { to: "/study", label: "Study", icon: Brain },
  { to: "/ask", label: "Ask", icon: MessagesSquare },
  { to: "/graph", label: "Graph", icon: GitBranch },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const config = useStore((state) => state.config);
  const vault = useStore((state) => state.vault);
  const setPalette = useStore((state) => state.setPalette);

  const streak = config?.streakDays ?? [];
  const streakNow = streak.includes(todayKey()) ? streak.length : 0;
  const total = vault?.lessons.length ?? 0;
  const concepts = vault?.concepts.length ?? 0;
  const mastery = total ? Math.min(100, Math.round((concepts / Math.max(1, total * 3)) * 100)) : 0;

  return (
    <aside className="flex h-full w-[248px] shrink-0 flex-col border-r bg-surface/60">
      <div className="flex items-center gap-3 px-5 pb-5 pt-6">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-accent to-iris text-sm font-bold text-white shadow-glow">
          S
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">Shellslatee</p>
          <p className="truncate text-[11px] text-muted">{vault?.title || "Study cockpit"}</p>
        </div>
      </div>

      <button
        onClick={() => setPalette(true)}
        className="mx-3 mb-4 flex items-center gap-2 rounded-xl border bg-bg/60 px-3 py-2 text-xs text-muted transition hover:border-accent/30 hover:text-ink"
      >
        <Command className="h-3.5 w-3.5" />
        <span className="flex-1 text-left">Jump to anything…</span>
        <span className="kbd">⌘K</span>
      </button>

      <nav className="flex flex-col gap-1 px-3">
        {nav.map((item) => {
          const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={cn("nav-item", active && "active")}
            >
              {active ? (
                <motion.span
                  layoutId="nav-glow"
                  className="absolute inset-0 -z-10 rounded-xl bg-accent/10"
                  transition={{ type: "spring", stiffness: 380, damping: 32 }}
                />
              ) : null}
              <item.icon className="h-4 w-4" />
              <span className="flex-1">{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="mx-3 mt-5 rounded-xl2 border bg-bg/50 p-3.5">
        <div className="flex items-center justify-between">
          <div>
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
              <Flame className={cn("h-3.5 w-3.5", streakNow > 0 ? "text-accent" : "text-muted")} />
              Streak
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {streakNow} <span className="text-xs font-normal text-muted">day{streakNow === 1 ? "" : "s"}</span>
            </p>
          </div>
          <ProgressRing value={mastery} size={40} label={`${mastery}%`} />
        </div>
        <p className="mt-2 text-[11px] leading-snug text-muted">
          {total ? `${total} lessons · ${concepts} concepts` : "Add a vault to begin"}
        </p>
      </div>

      <div className="mt-auto px-3 pb-4 pt-4">
        <NavLink to="/settings" onClick={onNavigate} className={({ isActive }) => cn("nav-item", isActive && "active")}>
          <Settings className="h-4 w-4" />
          <span className="flex-1">Settings</span>
        </NavLink>
        <div className="mt-3 flex items-center gap-2 px-1 text-[10px] text-muted">
          <Sparkles className="h-3 w-3 text-accent" />
          <span>Local-first · bring your own key</span>
        </div>
      </div>
    </aside>
  );
}
