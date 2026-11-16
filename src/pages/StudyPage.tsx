import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Brain,
  Check,
  CircleDot,
  Flame,
  Layers,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Target,
  Trophy,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ProgressRing, SectionHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { celebrate } from "@/lib/celebrate";
import { useStore } from "@/lib/store";
import type { Card as Flashcard, CardsQueue, DrillGroup, DrillQueue, QuizCheck, QuizItem, QuizQueue } from "@/lib/types";
import { cn, pct } from "@/lib/utils";

type Lane = "cards" | "drills" | "quiz";

export function StudyPage() {
  const config = useStore((state) => state.config);
  const notify = useStore((state) => state.notify);
  const [lane, setLane] = useState<Lane>("cards");

  if (!config?.vault) {
    return (
      <EmptyState
        icon={<Layers className="h-6 w-6" />}
        title="Nothing to study yet"
        body="Open a vault in Settings, then build cards and a quiz."
        action={<Link to="/settings" className="btn btn-primary btn-sm">Open settings</Link>}
      />
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
      <SectionHeader
        title="Study room"
        subtitle="Spaced repetition, weakness drills, and exam-style questions — built from your own notes."
      />
      <div className="flex gap-1 rounded-2xl border bg-surface/60 p-1">
        {(
          [
            { id: "cards", label: "Flashcards", icon: Layers, hint: "spaced repetition" },
            { id: "drills", label: "Weak spots", icon: Flame, hint: "targeted" },
            { id: "quiz", label: "Quiz", icon: Target, hint: "exam-style" },
          ] as const
        ).map((item) => (
          <button
            key={item.id}
            onClick={() => setLane(item.id)}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[12px] font-medium transition",
              lane === item.id ? "bg-accent/12 text-accent shadow-sm" : "text-muted hover:text-ink",
            )}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
            <span className="hidden text-[10px] font-normal opacity-60 sm:inline">{item.hint}</span>
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div key={lane} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
          {lane === "cards" ? <CardsLane notify={notify} vault={config.vault} /> : null}
          {lane === "drills" ? <DrillsLane notify={notify} vault={config.vault} /> : null}
          {lane === "quiz" ? <QuizLane notify={notify} vault={config.vault} /> : null}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  );
}

type Notify = (title: string, message?: string, tone?: "info" | "success" | "error") => void;

function CardsLane({ vault, notify }: { vault: string; notify: Notify }) {
  const [queue, setQueue] = useState<CardsQueue | null>(null);
  const [session, setSession] = useState<Flashcard[] | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [building, setBuilding] = useState(false);
  const [grades, setGrades] = useState<number[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await api.cards(vault, 30);
      setQueue(data);
      setSession(data.cards);
      setIndex(0);
      setFlipped(false);
      setGrades([]);
    } catch (err) {
      notify("Could not load cards", err instanceof Error ? err.message : String(err), "error");
    }
  }, [vault, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const grade = useCallback(
    async (value: number) => {
      const card = session?.[index];
      if (!card) return;
      setGrades((prev) => [...prev, value]);
      setFlipped(false);
      setIndex((prev) => prev + 1);
      try {
        await api.reviewCard(vault, card.id, value);
      } catch {
        /* review persistence is best-effort; session continues */
      }
      if (value >= 3) celebrate("session");
    },
    [session, index, vault],
  );

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return;
      if (event.code === "Space") {
        event.preventDefault();
        setFlipped((prev) => !prev);
      }
      if (flipped && ["1", "2", "3", "4"].includes(event.key)) {
        event.preventDefault();
        void grade(Number(event.key));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [flipped, grade]);

  if (!queue) {
    return <div className="space-y-3">{[0, 1].map((i) => <Skeleton key={i} className="h-64 w-full" />)}</div>;
  }

  const stats = queue.stats;
  const total = stats.total;
  const current = session?.[index];

  if (!current && total === 0) {
    return (
      <EmptyState
        icon={<Layers className="h-6 w-6" />}
        title="No cards in the vault"
        body="Shellslatee can turn every note into question/answer cards, scheduled with FSRS."
        action={
          <Button
            loading={building}
            onClick={async () => {
              setBuilding(true);
              try {
                const result = await api.buildCards(vault);
                notify("Cards built", `${result.total} total · ${result.created} new`, "success");
                await load();
              } catch (err) {
                notify("Build failed", err instanceof Error ? err.message : String(err), "error");
              } finally {
                setBuilding(false);
              }
            }}
          >
            Build cards from notes
          </Button>
        }
      />
    );
  }

  if (!current) {
    const remembered = grades.filter((value) => value >= 3).length;
    return (
      <Card className="flex flex-col items-center gap-4 p-10 text-center">
        <div className="grid h-16 w-16 place-items-center rounded-full bg-good/12 text-good">
          <Trophy className="h-7 w-7" />
        </div>
        <div>
          <p className="font-display text-2xl">That's the deck, chef.</p>
          <p className="mt-1 text-sm text-muted">
            {grades.length} reviewed · {remembered} landed · {pct(remembered, Math.max(1, grades.length))}% recall this session
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void load()} icon={<RefreshCw className="h-4 w-4" />}>Reload queue</Button>
          <Link to="/library" className="btn btn-primary btn-md">Back to library</Link>
        </div>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_240px]">
      <div className="space-y-3">
        <div className="flex items-center justify-between text-[11px] text-muted">
          <span>{index + 1} / {session?.length ?? 0}</span>
          <span>{stats.due} due · {stats.new} new · {stats.total} total</span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-line">
          <motion.div className="h-full rounded-full bg-accent" animate={{ width: `${pct(index, Math.max(1, session?.length ?? 1))}%` }} transition={{ ease: [0.22, 1, 0.36, 1] }} />
        </div>

        <div className="flip-card h-[320px] cursor-pointer select-none" onClick={() => setFlipped((prev) => !prev)}>
          <div className={cn("flip-inner", flipped && "flipped")}>
            <div className="flip-face card flex flex-col items-center justify-center gap-4 p-10 text-center">
              <Badge tone="iris"><Brain className="h-3 w-3" />{current.kind || "concept"}</Badge>
              <p className="font-display text-xl leading-snug md:text-2xl">{current.front}</p>
              <p className="absolute bottom-5 text-[10px] uppercase tracking-wider text-muted">click or space to flip</p>
            </div>
            <div className="flip-face flip-back card flex flex-col justify-center gap-3 overflow-y-auto p-8">
              <p className="text-[10px] uppercase tracking-wider text-muted">Answer</p>
              <p className="text-[14px] leading-relaxed">{current.back}</p>
              {current.concept ? <Badge tone="muted">{current.concept}</Badge> : null}
            </div>
          </div>
        </div>

        <AnimatePresence mode="wait">
          {flipped ? (
            <motion.div key="grades" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="grid grid-cols-4 gap-2">
              {[
                { grade: 1, label: "Again", tone: "text-bad border-bad/30 hover:bg-bad/10", key: "1" },
                { grade: 2, label: "Hard", tone: "text-warn border-warn/30 hover:bg-warn/10", key: "2" },
                { grade: 3, label: "Good", tone: "text-accent border-accent/30 hover:bg-accent/10", key: "3" },
                { grade: 4, label: "Easy", tone: "text-good border-good/30 hover:bg-good/10", key: "4" },
              ].map((item) => (
                <button
                  key={item.grade}
                  onClick={(event) => {
                    event.stopPropagation();
                    void grade(item.grade);
                  }}
                  className={cn("rounded-xl border bg-surface/60 py-2.5 text-[12px] font-medium transition active:scale-[0.98]", item.tone)}
                >
                  {item.label}
                  <span className="ml-1.5 text-[10px] opacity-50">{item.key}</span>
                </button>
              ))}
            </motion.div>
          ) : (
            <motion.p key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-center text-[11px] text-muted">
              Recall first. Flip when you've got it — grading is what schedules the next review.
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      <SideStats stats={stats} grades={grades} />
    </div>
  );
}

function SideStats({ stats, grades }: { stats: CardsQueue["stats"]; grades: number[] }) {
  const remembered = grades.filter((value) => value >= 3).length;
  return (
    <Card className="h-fit space-y-4 p-4">
      <div className="flex items-center gap-3">
        <ProgressRing value={pct(stats.due, Math.max(1, stats.total))} size={56} stroke={5} label={String(stats.due)} />
        <div>
          <p className="text-[12px] font-medium">Due now</p>
          <p className="text-[11px] text-muted">{stats.total} cards tracked</p>
        </div>
      </div>
      <div className="space-y-2 border-t pt-3 text-[11px]">
        <div className="flex justify-between"><span className="text-muted">New</span><span>{stats.new}</span></div>
        <div className="flex justify-between"><span className="text-muted">Reviewed</span><span>{grades.length}</span></div>
        <div className="flex justify-between"><span className="text-muted">Landed</span><span className="text-good">{remembered}</span></div>
      </div>
      <div className="rounded-lg bg-bg/60 p-2.5 text-[10px] leading-relaxed text-muted">
        Grades feed FSRS: <span className="text-bad">Again</span> resets, <span className="text-accent">Good</span> grows the interval,
        <span className="text-good"> Easy</span> pushes it out furthest.
      </div>
    </Card>
  );
}

function DrillsLane({ vault, notify }: { vault: string; notify: Notify }) {
  const [queue, setQueue] = useState<DrillQueue | null>(null);
  const [active, setActive] = useState<DrillGroup | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .drills(vault, 20)
      .then((data) => {
        if (!cancelled) setQueue(data);
      })
      .catch((err) => notify("Could not load weak spots", err instanceof Error ? err.message : String(err), "error"));
    return () => {
      cancelled = true;
    };
  }, [vault, notify]);

  if (active) {
    return <DrillSession group={active} vault={vault} notify={notify} onDone={() => setActive(null)} />;
  }

  if (!queue) return <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full" />)}</div>;

  if (queue.groups.length === 0) {
    return (
      <EmptyState
        icon={<Flame className="h-6 w-6" />}
        title="No weak spots detected"
        body="Once you review cards, the ones that keep slipping get clustered here by concept. Study a deck first, or build more cards."
        action={<Link to="/library" className="btn btn-primary btn-sm">Open library</Link>}
      />
    );
  }

  const maxWeakness = Math.max(1, ...queue.groups.map((group) => group.weakness));

  return (
    <div className="space-y-3">
      <Card className="flex items-center justify-between gap-4 p-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-bad/10 text-bad"><Flame className="h-5 w-5" /></div>
          <div>
            <p className="text-[13px] font-medium">Confusion heatmap</p>
            <p className="text-[11px] text-muted">The concepts your reviews keep flagging — clustered, ranked, ready.</p>
          </div>
        </div>
        <Badge tone="bad">{queue.stats.due} due</Badge>
      </Card>

      {queue.groups.map((group) => {
        const ratio = group.weakness / maxWeakness;
        return (
          <Card key={`${group.lesson}-${group.concept ?? "all"}`} className="flex items-center gap-4 p-4">
            <div className="w-16 shrink-0">
              <div className="h-1.5 overflow-hidden rounded-full bg-line">
                <div
                  className={cn("h-full rounded-full", ratio > 0.66 ? "bg-bad" : ratio > 0.33 ? "bg-warn" : "bg-good")}
                  style={{ width: `${Math.max(8, Math.round(ratio * 100))}%` }}
                />
              </div>
              <p className="mt-1 text-center text-[10px] text-muted">{group.weakness.toFixed(1)} score</p>
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{group.concept ?? "General recall"}</p>
              <p className="truncate text-[11px] text-muted">{group.lesson} · {group.cards.length} cards</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => setActive(group)} icon={<Zap className="h-3.5 w-3.5" />}>
              Drill
            </Button>
          </Card>
        );
      })}
    </div>
  );
}

function DrillSession({
  group,
  vault,
  notify,
  onDone,
}: {
  group: DrillGroup;
  vault: string;
  notify: Notify;
  onDone: () => void;
}) {
  const cards = group.cards;
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [done, setDone] = useState(0);

  const grade = async (value: number) => {
    const card = cards[index];
    if (!card) return;
    if (value >= 3) setDone((prev) => prev + 1);
    setFlipped(false);
    setIndex((prev) => prev + 1);
    try {
      await api.reviewCard(vault, card.id, value);
    } catch {
      notify("Review not saved", "The session keeps going — the engine will re-sync.", "info");
    }
  };

  if (index >= cards.length) {
    return (
      <Card className="flex flex-col items-center gap-3 p-10 text-center">
        <div className="grid h-14 w-14 place-items-center rounded-full bg-good/12 text-good"><Check className="h-6 w-6" /></div>
        <p className="font-display text-xl">Weak spot drilled.</p>
        <p className="text-sm text-muted">{done} of {cards.length} landed this pass.</p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { setIndex(0); setDone(0); }} icon={<RotateCcw className="h-4 w-4" />}>Run it again</Button>
          <Button onClick={onDone}>Back to weak spots</Button>
        </div>
      </Card>
    );
  }

  const card = cards[index];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button onClick={onDone} className="btn btn-ghost btn-sm"><X className="h-3.5 w-3.5" />Exit drill</button>
        <Badge tone="bad"><Flame className="h-3 w-3" />{group.concept ?? "recall"}</Badge>
      </div>
      <div className="flip-card h-[300px]" onClick={() => setFlipped((prev) => !prev)}>
        <div className={cn("flip-inner cursor-pointer", flipped && "flipped")}>
          <div className="flip-face card flex flex-col items-center justify-center gap-3 p-10 text-center">
            <p className="font-display text-xl leading-snug">{card.front}</p>
            <p className="text-[10px] uppercase tracking-wider text-muted">{index + 1} / {cards.length} · click to flip</p>
          </div>
          <div className="flip-face flip-back card flex flex-col justify-center gap-3 p-8">
            <p className="text-[10px] uppercase tracking-wider text-muted">Answer</p>
            <p className="text-[14px] leading-relaxed">{card.back}</p>
          </div>
        </div>
      </div>
      {flipped ? (
        <div className="grid grid-cols-4 gap-2">
          {[1, 2, 3, 4].map((value) => (
            <button key={value} onClick={() => void grade(value)} className="rounded-xl border bg-surface/60 py-2.5 text-[12px] font-medium transition hover:bg-accent/10">
              {["Again", "Hard", "Good", "Easy"][value - 1]}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function QuizLane({ vault, notify }: { vault: string; notify: Notify }) {
  const [queue, setQueue] = useState<QuizQueue | null>(null);
  const [index, setIndex] = useState(0);
  const [response, setResponse] = useState("");
  const [result, setResult] = useState<QuizCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [score, setScore] = useState({ correct: 0, answered: 0 });
  const [building, setBuilding] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.quiz(vault, 20);
      setQueue(data);
      setIndex(0);
      setResponse("");
      setResult(null);
      setScore({ correct: 0, answered: 0 });
    } catch (err) {
      notify("Could not load quiz", err instanceof Error ? err.message : String(err), "error");
    }
  }, [vault, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [index]);

  if (!queue) return <div className="space-y-3">{[0, 1].map((i) => <Skeleton key={i} className="h-48 w-full" />)}</div>;

  const items = queue.items;
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<Target className="h-6 w-6" />}
        title="No quiz questions yet"
        body="Build a quiz from your notes — MCQ and short-answer, graded instantly."
        action={
          <Button
            loading={building}
            onClick={async () => {
              setBuilding(true);
              try {
                const built = await api.buildQuiz(vault);
                notify("Quiz built", `${built.total} questions`, "success");
                await load();
              } catch (err) {
                notify("Build failed", err instanceof Error ? err.message : String(err), "error");
              } finally {
                setBuilding(false);
              }
            }}
          >
            Build quiz
          </Button>
        }
      />
    );
  }

  if (index >= items.length) {
    const accuracy = pct(score.correct, Math.max(1, score.answered));
    return (
      <Card className="flex flex-col items-center gap-4 p-10 text-center">
        <div className="grid h-16 w-16 place-items-center rounded-full bg-accent/12 text-accent"><Trophy className="h-7 w-7" /></div>
        <p className="font-display text-2xl">{accuracy >= 80 ? "Exam-ready energy." : "Good rep — go again."}</p>
        <p className="text-sm text-muted">{score.correct} / {score.answered} correct · {accuracy}%</p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void load()} icon={<RefreshCw className="h-4 w-4" />}>New round</Button>
          <Link to="/ask" className="btn btn-primary btn-md">Ask the tutor</Link>
        </div>
      </Card>
    );
  }

  const item: QuizItem = items[index];

  const check = async (answer: string) => {
    if (!answer.trim() || checking) return;
    setChecking(true);
    try {
      const checked = await api.checkQuiz(vault, item.id, answer);
      setResult(checked);
      setScore((prev) => ({ correct: prev.correct + (checked.correct ? 1 : 0), answered: prev.answered + 1 }));
      if (checked.correct) celebrate("session");
    } catch (err) {
      notify("Check failed", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setChecking(false);
    }
  };

  const next = () => {
    setIndex((prev) => prev + 1);
    setResponse("");
    setResult(null);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
      <Card className="space-y-4 p-5 md:p-6">
        <div className="flex items-center justify-between">
          <Badge tone="iris">{item.kind === "mcq" ? "Multiple choice" : "Short answer"}</Badge>
          <span className="text-[11px] text-muted">{index + 1} / {items.length}</span>
        </div>

        <p className="font-display text-lg leading-snug">{item.question}</p>

        {item.kind === "mcq" ? (
          <div className="space-y-2">
            {item.options.map((option, optionIndex) => {
              const chosen = response === String(optionIndex);
              const showCorrect = result && result.answer_index === optionIndex;
              const showWrong = result && chosen && !result.correct;
              return (
                <button
                  key={optionIndex}
                  disabled={Boolean(result)}
                  onClick={() => {
                    setResponse(String(optionIndex));
                    void check(String(optionIndex));
                  }}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl border bg-surface/40 px-3.5 py-2.5 text-left text-[13px] transition",
                    showCorrect && "border-good/50 bg-good/10",
                    showWrong && "border-bad/50 bg-bad/10",
                    !result && chosen && "border-accent/50",
                    !result && "hover:border-accent/35 hover:bg-accent/5",
                  )}
                >
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg border text-[11px]">
                    {showCorrect ? <Check className="h-3.5 w-3.5 text-good" /> : showWrong ? <X className="h-3.5 w-3.5 text-bad" /> : String.fromCharCode(65 + optionIndex)}
                  </span>
                  {option}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="space-y-2">
            <textarea
              ref={inputRef}
              value={response}
              onChange={(event) => setResponse(event.target.value)}
              disabled={Boolean(result)}
              placeholder="Answer in your own words…"
              className="input min-h-24 resize-y text-[13px]"
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void check(response);
              }}
            />
            {!result ? (
              <Button size="sm" loading={checking} disabled={!response.trim()} onClick={() => void check(response)}>
                Check answer
              </Button>
            ) : null}
          </div>
        )}

        <AnimatePresence>
          {result ? (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cn("rounded-xl border p-3.5", result.correct ? "border-good/30 bg-good/5" : "border-bad/30 bg-bad/5")}>
              <p className={cn("flex items-center gap-1.5 text-[12px] font-semibold", result.correct ? "text-good" : "text-bad")}>
                {result.correct ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
                {result.correct ? "Correct" : "Not quite"}
              </p>
              {!result.correct ? <p className="mt-1 text-[12px]"><span className="text-muted">Answer:</span> {result.answer}</p> : null}
              {result.explanation ? <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{result.explanation}</p> : null}
              <Button size="sm" className="mt-2.5" onClick={next} icon={<ArrowRight className="h-3.5 w-3.5" />}>
                {index + 1 >= items.length ? "Finish" : "Next question"}
              </Button>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </Card>

      <Card className="h-fit space-y-3 p-4">
        <div className="flex items-center gap-2 text-[12px] font-medium"><CircleDot className="h-3.5 w-3.5 text-accent" />Round</div>
        <div className="flex items-center gap-3">
          <ProgressRing value={pct(score.correct, Math.max(1, score.answered))} size={54} stroke={5} label={`${pct(score.correct, Math.max(1, score.answered))}%`} />
          <div className="text-[11px]">
            <p>{score.correct} correct</p>
            <p className="text-muted">{score.answered} answered</p>
          </div>
        </div>
        <div className="space-y-1 border-t pt-3 text-[11px]">
          <div className="flex justify-between"><span className="text-muted">Pool</span><span>{queue.stats.total}</span></div>
          <div className="flex justify-between"><span className="text-muted">MCQ</span><span>{queue.stats.mcq}</span></div>
          <div className="flex justify-between"><span className="text-muted">Short</span><span>{queue.stats.short}</span></div>
        </div>
        <div className="rounded-lg bg-bg/60 p-2.5 text-[10px] leading-relaxed text-muted">
          Wrong answers feed the weak-spot heatmap. <Sparkles className="inline h-3 w-3" /> Toggle Weak spots after a round.
        </div>
      </Card>
    </div>
  );
}
