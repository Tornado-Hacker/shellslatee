import { motion } from "framer-motion";
import {
  ArrowRight,
  BookOpen,
  Brain,
  CalendarClock,
  Clock3,
  Flame,
  Play,
  Sparkles,
  Target,
  Wand2,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { riseItem, stagger } from "@/lib/motion";
import { useStore } from "@/lib/store";
import type { CardsQueue, DrillQueue } from "@/lib/types";
import { cn, compactNumber, daysUntil, formatDuration, greeting, pct, todayKey } from "@/lib/utils";
import { Badge, Button, Card, EmptyState, ProgressRing, SectionHeader, Skeleton } from "@/components/ui";

export function HomePage() {
  const config = useStore((state) => state.config);
  const vault = useStore((state) => state.vault);
  const update = useStore((state) => state.update);
  const setIngest = useStore((state) => state.setIngest);
  const navigate = useNavigate();
  const [cards, setCards] = useState<CardsQueue | null>(null);
  const [drills, setDrills] = useState<DrillQueue | null>(null);
  const [loading, setLoading] = useState(true);

  const vaultPath = config?.vault ?? "";
  const source = config?.source ?? "";

  useEffect(() => {
    if (!vaultPath) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([api.cards(vaultPath, 30), api.drills(vaultPath, 12)])
      .then(([cardData, drillData]) => {
        if (!cancelled) {
          setCards(cardData);
          setDrills(drillData);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCards(null);
          setDrills(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [vaultPath, source]);

  useEffect(() => {
    if (!config) return;
    const key = todayKey();
    if (!config.streakDays.includes(key)) {
      const pruned = [...config.streakDays.filter((day) => day !== key), key].slice(-90);
      void update({ streakDays: pruned });
    }
  }, [config, update]);

  const lessons = vault?.lessons ?? [];
  const concepts = vault?.concepts ?? [];
  const lastLesson = useMemo(
    () => lessons.find((lesson) => lesson.rel === config?.lastNote) ?? lessons[0],
    [lessons, config?.lastNote],
  );

  const due = cards?.stats.due ?? 0;
  const newCards = cards?.stats.new ?? 0;
  const weak = (drills?.groups ?? []).slice(0, 5);
  const examDays = daysUntil(config?.examDate);
  const dailyMinutes = config?.dailyMinutes ?? 25;
  const planMinutes = Math.min(dailyMinutes, Math.max(8, Math.round(due * 0.8 + weak.length * 3)));
  const streak = config?.streakDays.includes(todayKey()) ? config?.streakDays.length ?? 0 : 0;
  const mastery = concepts.length ? pct(concepts.length, Math.max(1, lessons.length * 3)) : 0;

  const hour = new Date().getHours();
  const vibe =
    hour < 5 ? "The house is quiet. Good time for one hard concept." :
    hour < 12 ? "Start with the thing you keep avoiding." :
    hour < 18 ? "A short session now beats a long one at midnight." :
    "Wind down with recall, not rereading.";

  if (!vault) {
    return (
      <div className="space-y-5">
        <Header greetingText={greeting()} />
        <EmptyState
          icon={<BookOpen className="h-6 w-6" />}
          title="No vault loaded yet"
          body="Point Shellslatee at a notes folder, or generate notes from a course folder of videos, PDFs and slides."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button onClick={() => setIngest(true)} icon={<Wand2 className="h-4 w-4" />}>Build from a folder</Button>
              <Button variant="outline" onClick={() => navigate("/settings")}>Open settings</Button>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <motion.div variants={stagger} initial="initial" animate="enter" className="space-y-7">
      <Header greetingText={config?.examTitle ? "Exam season" : greeting()} vibe={vibe} />

      <motion.section variants={riseItem} className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Card className="relative overflow-hidden p-0">
          <div className="absolute inset-0 bg-gradient-to-br from-accent/18 via-transparent to-iris/18" />
          <div className="relative flex h-full flex-col justify-between gap-6 p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-accent">
                  <Play className="h-3 w-3" /> Continue
                </p>
                <h2 className="mt-2 max-w-md text-2xl font-semibold leading-tight">
                  {lastLesson?.title ?? "Your first lesson"}
                </h2>
                <p className="mt-1.5 line-clamp-2 max-w-md text-sm text-muted">
                  {lastLesson?.summary || "Generate notes and they will show up here, ready to read."}
                </p>
              </div>
              <ProgressRing value={mastery} size={62} stroke={5} label={`${mastery}%`} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {lastLesson ? (
                <Button
                  onClick={() => navigate(`/note/${encodeURIComponent(lastLesson.rel)}`)}
                  icon={<ArrowRight className="h-4 w-4" />}
                >
                  Open lesson
                </Button>
              ) : null}
              <div className="flex items-center gap-2 text-[11px] text-muted">
                <Clock3 className="h-3.5 w-3.5" />
                {formatDuration(lastLesson?.duration)} · {lastLesson?.module || "unfiled"}
              </div>
            </div>
          </div>
        </Card>

        <Card className="flex flex-col justify-between p-5">
          <div>
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
              <Target className="h-3 w-3" /> Today's plan
            </p>
            {loading ? (
              <div className="mt-3 space-y-2">
                <Skeleton className="h-8 w-32" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ) : (
              <>
                <p className="mt-2 text-3xl font-semibold tabular-nums">
                  {planMinutes}
                  <span className="ml-1 text-sm font-normal text-muted">min</span>
                </p>
                <p className="mt-1 text-sm text-muted">
                  {due + newCards > 0
                    ? `${due} due · ${newCards} new · ${weak.length} weak concept${weak.length === 1 ? "" : "s"}`
                    : "Nothing due. A quick explain-back keeps it warm."}
                </p>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line">
                  <motion.div
                    className="h-full rounded-full bg-accent"
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(100, pct(planMinutes, dailyMinutes))}%` }}
                    transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
              </>
            )}
          </div>
          <div className="mt-4 flex gap-2">
            <Button size="sm" onClick={() => navigate("/study")} icon={<Zap className="h-3.5 w-3.5" />}>
              Start recall
            </Button>
            <Button size="sm" variant="ghost" onClick={() => navigate("/ask")}>
              Ask instead
            </Button>
          </div>
        </Card>
      </motion.section>

      <motion.section variants={riseItem} className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat icon={<BookOpen className="h-4 w-4" />} label="Lessons" value={compactNumber(lessons.length)} />
        <Stat icon={<Sparkles className="h-4 w-4" />} label="Concepts" value={compactNumber(concepts.length)} />
        <Stat icon={<Brain className="h-4 w-4" />} label="Due today" value={compactNumber(due + newCards)} accent />
        <Stat icon={<Flame className="h-4 w-4" />} label="Streak" value={`${streak}d`} />
      </motion.section>

      <motion.section variants={riseItem}>
        <SectionHeader
          title="Study cockpit"
          subtitle="The one thing no other note app does: a plan that knows what you keep forgetting."
          action={
            config?.examDate ? (
              <Badge tone={examDays !== null && examDays <= 7 ? "bad" : "accent"}>
                <CalendarClock className="h-3 w-3" />
                {examDays !== null && examDays >= 0 ? `${examDays} day${examDays === 1 ? "" : "s"} to exam` : "exam passed"}
              </Badge>
            ) : null
          }
        />
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <ExamCard />
          <Card className="p-5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Weak spots</p>
            {weak.length === 0 ? (
              <p className="mt-3 text-sm text-muted">
                {loading ? "Reading your recall history…" : "No lapses recorded yet. Review a few cards and this fills in."}
              </p>
            ) : (
              <div className="mt-3 space-y-3">
                {weak.map((group) => {
                  const maxWeakness = Math.max(1, ...weak.map((item) => item.weakness));
                  const strength = Math.max(8, Math.min(100, 100 - (group.weakness / maxWeakness) * 100));
                  return (
                    <Link
                      key={`${group.concept}-${group.lesson}`}
                      to={`/note/${encodeURIComponent(group.lesson)}`}
                      className="group block"
                    >
                      <div className="flex items-center justify-between gap-3 text-[13px]">
                        <span className="truncate font-medium group-hover:text-accent">
                          {group.concept || "unfiled concept"}
                        </span>
                        <span className="shrink-0 text-[11px] text-muted">{group.cards.length} card{group.cards.length === 1 ? "" : "s"}</span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-line">
                        <motion.div
                          className={cn("h-full rounded-full", strength < 35 ? "bg-bad" : strength < 65 ? "bg-warn" : "bg-good")}
                          initial={{ width: 0 }}
                          animate={{ width: `${strength}%` }}
                          transition={{ duration: 0.7 }}
                        />
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </motion.section>

      <motion.section variants={riseItem}>
        <SectionHeader
          title="Recent lessons"
          subtitle={vault.title}
          action={<Link to="/library" className="btn btn-ghost btn-sm">All lessons <ArrowRight className="h-3.5 w-3.5" /></Link>}
        />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {lessons.slice(0, 6).map((lesson) => (
            <Link key={lesson.rel} to={`/note/${encodeURIComponent(lesson.rel)}`} className="card card-hover group p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="line-clamp-2 text-[13px] font-semibold leading-snug group-hover:text-accent">{lesson.title}</p>
                <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-accent" />
              </div>
              <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-muted">{lesson.summary}</p>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge tone="muted"><Clock3 className="h-3 w-3" />{formatDuration(lesson.duration)}</Badge>
                {lesson.concepts.slice(0, 2).map((concept) => (
                  <Badge key={concept} tone="iris">{concept.replace(/^con_/, "").replace(/-/g, " ")}</Badge>
                ))}
              </div>
            </Link>
          ))}
        </div>
      </motion.section>
    </motion.div>
  );
}

function Header({ greetingText, vibe }: { greetingText: string; vibe?: string }) {
  const config = useStore((state) => state.config);
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">Study cockpit</p>
        <h2 className="mt-1 font-display text-3xl tracking-tight md:text-[34px]">
          {greetingText}
          {config && !config.examTitle ? ", ready to recall?" : "."}
        </h2>
        {vibe ? <p className="mt-1 text-sm text-muted">{vibe}</p> : null}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => useStore.getState().setIngest(true)} icon={<Wand2 className="h-3.5 w-3.5" />}>
          Add source
        </Button>
        <p className="text-[11px] text-muted">
          {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
        </p>
      </div>
    </header>
  );
}

function Stat({ icon, label, value, accent }: { icon: React.ReactNode; label: string; value: string; accent?: boolean }) {
  return (
    <div className={cn("stat flex items-center gap-3", accent && "border-accent/25 bg-accent/5")}>
      <div className={cn("grid h-9 w-9 place-items-center rounded-xl", accent ? "bg-accent/15 text-accent" : "bg-ink/5 text-muted")}>
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{label}</p>
        <p className="text-xl font-semibold tabular-nums leading-tight">{value}</p>
      </div>
    </div>
  );
}

function ExamCard() {
  const config = useStore((state) => state.config);
  const update = useStore((state) => state.update);
  const [title, setTitle] = useState(config?.examTitle ?? "");
  const [date, setDate] = useState(config?.examDate ?? "");
  const [minutes, setMinutes] = useState(String(config?.dailyMinutes ?? 25));
  const days = daysUntil(date);
  const dirty = title !== (config?.examTitle ?? "") || date !== (config?.examDate ?? "") || minutes !== String(config?.dailyMinutes ?? 25);

  const save = () =>
    update({
      examTitle: title.trim(),
      examDate: date,
      dailyMinutes: Math.max(5, Math.min(240, Number(minutes) || 25)),
    });

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
          <Target className="h-3 w-3" /> Exam mode
        </p>
        {days !== null ? (
          <Badge tone={days <= 7 ? "bad" : days <= 21 ? "warn" : "good"}>
            {days >= 0 ? `${days} days out` : "past"}
          </Badge>
        ) : (
          <Badge tone="muted">optional</Badge>
        )}
      </div>
      <p className="mt-2 text-sm text-muted">
        Name the exam and a date. The cockpit weights today's plan toward weak concepts and
        counts down without a panic spiral.
      </p>
      <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
        <div>
          <label className="label">Exam</label>
          <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Networks midterm" />
        </div>
        <div>
          <label className="label">Date</label>
          <input className="input" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </div>
        <div>
          <label className="label">Daily minutes</label>
          <input className="input" type="number" min={5} max={240} value={minutes} onChange={(event) => setMinutes(event.target.value)} />
        </div>
        <div className="flex items-end">
          <Button size="sm" onClick={save} disabled={!dirty} loading={false}>
            Save plan
          </Button>
        </div>
      </div>
    </Card>
  );
}
