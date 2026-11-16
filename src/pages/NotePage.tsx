import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  BookOpenCheck,
  Brain,
  Clock3,
  GraduationCap,
  ListTree,
  Loader2,
  MessageSquare,
  Pencil,
  Play,
  Save,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Markdown } from "@/components/Markdown";
import { Badge, Button, Card, EmptyState, Input, Skeleton } from "@/components/ui";
import { api, mediaUrl } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { Card as CardType, Citation, Note, QuizItem } from "@/lib/types";
import { cn, formatClock, formatDuration } from "@/lib/utils";

type Tab = "outline" | "recall" | "explain" | "ask";

export function NotePage() {
  const params = useParams();
  const navigate = useNavigate();
  const rel = useMemo(() => {
    const raw = params["*"] ?? "";
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }, [params]);

  const config = useStore((state) => state.config);
  const update = useStore((state) => state.update);
  const notify = useStore((state) => state.notify);

  const [note, setNote] = useState<Note | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("outline");
  const [headings, setHeadings] = useState<{ id: string; text: string; level: number }[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [activeHeading, setActiveHeading] = useState("");

  const vault = config?.vault ?? "";
  const source = config?.source ?? "";

  useEffect(() => {
    if (!vault || !rel) {
      setError("No lesson selected.");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .note(vault, rel, source || undefined)
      .then((data) => {
        if (cancelled) return;
        setNote(data);
        void update({ lastNote: rel, lastOpened: Date.now() });
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vault, rel, source]);

  const seek = useCallback((start: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, start);
    void video.play().catch(() => undefined);
  }, []);

  const onHeading = useCallback((list: { id: string; text: string; level: number }[]) => {
    setHeadings(list);
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    );
  }

  if (error || !note) {
    return (
      <EmptyState
        icon={<BookOpenCheck className="h-6 w-6" />}
        title="Could not open this lesson"
        body={error ?? "The note may have moved."}
        action={<Button variant="outline" onClick={() => navigate("/library")}>Back to library</Button>}
      />
    );
  }

  const videoSrc = mediaUrl(note.video);
  const frontmatter = note.frontmatter ?? {};
  const duration = Number(frontmatter.duration ?? 0);

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
      <div className="flex items-start gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)} aria-label="Back">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {frontmatter.module ? <Badge tone="muted">{frontmatter.module}</Badge> : null}
            <Badge tone="muted"><Clock3 className="h-3 w-3" />{formatDuration(duration)}</Badge>
            {note.video ? <Badge tone="iris">video</Badge> : null}
          </div>
          <h1 className="mt-2 font-display text-2xl leading-tight md:text-3xl">{note.title}</h1>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-4">
          {videoSrc ? (
            <Card className="overflow-hidden p-0">
              <video ref={videoRef} src={videoSrc} controls className="aspect-video w-full bg-black" preload="metadata" />
            </Card>
          ) : null}
          <Card className="p-5 md:p-7">
            <NoteBody
              note={note}
              onHeading={onHeading}
              onSeek={seek}
              onActiveHeading={setActiveHeading}
              vault={vault}
              notify={notify}
            />
          </Card>
        </div>

        <aside className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Card className="overflow-hidden p-0">
            <div className="flex gap-1 border-b p-1.5">
              {(
                [
                  { id: "outline", label: "Outline", icon: ListTree },
                  { id: "recall", label: "Recall", icon: Brain },
                  { id: "explain", label: "Explain", icon: GraduationCap },
                  { id: "ask", label: "Ask", icon: MessageSquare },
                ] as const
              ).map((item) => (
                <button
                  key={item.id}
                  onClick={() => setTab(item.id)}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-medium transition",
                    tab === item.id ? "bg-accent/12 text-accent" : "text-muted hover:text-ink",
                  )}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  {item.label}
                </button>
              ))}
            </div>
            <div className="max-h-[calc(100vh-220px)] overflow-y-auto p-3">
              <AnimatePresence mode="wait">
                <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.16 }}>
                  {tab === "outline" ? (
                    <Outline headings={headings} segments={note.segments} active={activeHeading} onSeek={seek} />
                  ) : null}
                  {tab === "recall" ? <RecallTab rel={rel} vault={vault} /> : null}
                  {tab === "explain" ? <ExplainTab note={note} vault={vault} /> : null}
                  {tab === "ask" ? <AskTab note={note} vault={vault} source={source} /> : null}
                </motion.div>
              </AnimatePresence>
            </div>
          </Card>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              icon={<Wand2 className="h-3.5 w-3.5" />}
              onClick={async () => {
                try {
                  const result = await api.buildCards(vault);
                  notify("Cards rebuilt", `${result.total} total · ${result.created} new`, "success");
                } catch (err) {
                  notify("Card build failed", err instanceof Error ? err.message : String(err), "error");
                }
              }}
            >
              Build cards
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<Sparkles className="h-3.5 w-3.5" />}
              onClick={async () => {
                try {
                  const result = await api.buildQuiz(vault);
                  notify("Quiz rebuilt", `${result.total} questions`, "success");
                } catch (err) {
                  notify("Quiz build failed", err instanceof Error ? err.message : String(err), "error");
                }
              }}
            >
              Build quiz
            </Button>
          </div>
        </aside>
      </div>
    </motion.div>
  );
}

function NoteBody({
  note,
  onHeading,
  onSeek,
  onActiveHeading,
  vault,
  notify,
}: {
  note: Note;
  onHeading: (headings: { id: string; text: string; level: number }[]) => void;
  onSeek: (start: number) => void;
  onActiveHeading: (id: string) => void;
  vault: string;
  notify: (title: string, message?: string, tone?: "info" | "success" | "error") => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.markdown);
  const rendered = useMemo(
    () => note.markdown.replace(/\]\(([^)]*?)#t=(\d+(?:\.\d+)?)\)/g, "](#t=$2)"),
    [note.markdown],
  );
  const [saving, setSaving] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraft(note.markdown);
  }, [note.markdown]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || editing) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) onActiveHeading(entry.target.id);
        }
      },
      { rootMargin: "-15% 0px -70% 0px" },
    );
    node.querySelectorAll("h1,h2,h3").forEach((heading) => observer.observe(heading));
    return () => observer.disconnect();
  }, [note.markdown, editing, onActiveHeading]);

  const save = async () => {
    setSaving(true);
    try {
      const result = await api.saveNote({ out: vault, rel: note.rel, markdown: draft });
      notify("Lesson saved", result.bytes + " bytes", "success");
      setEditing(false);
      note.markdown = draft;
    } catch (err) {
      notify("Save failed", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div ref={scrollRef}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-[11px] uppercase tracking-wider text-muted">{editing ? "Editing Markdown" : "Lecture note"}</p>
        <div className="flex gap-1.5">
          {editing ? (
            <>
              <Button variant="ghost" size="sm" onClick={() => { setEditing(false); setDraft(note.markdown); }} icon={<X className="h-3.5 w-3.5" />}>Cancel</Button>
              <Button size="sm" loading={saving} onClick={save} icon={<Save className="h-3.5 w-3.5" />}>Save</Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)} icon={<Pencil className="h-3.5 w-3.5" />}>Edit</Button>
          )}
        </div>
      </div>
      {editing ? (
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="input min-h-[60vh] font-mono text-[12px] leading-relaxed"
          spellCheck={false}
        />
      ) : (
        <Markdown markdown={rendered} onHeading={onHeading} onTimestamp={onSeek} />
      )}
      {note.segments.length > 0 ? (
        <div className="mt-6 flex flex-wrap gap-1.5 border-t pt-4">
          <span className="mr-1 text-[11px] text-muted">Jump to:</span>
          {note.segments.slice(0, 12).map((segment) => (
            <button
              key={`${segment.start}-${segment.heading}`}
              onClick={() => onSeek(segment.start)}
              className="chip transition hover:border-accent/40 hover:text-accent"
            >
              <Play className="h-2.5 w-2.5" />
              {formatClock(segment.start)} · {segment.heading.replace(/^#+\s*/, "").slice(0, 32)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Outline({
  headings,
  segments,
  active,
  onSeek,
}: {
  headings: { id: string; text: string; level: number }[];
  segments: { start: number; heading: string }[];
  active: string;
  onSeek: (start: number) => void;
}) {
  const stamped = useMemo(() => {
    const map = new Map(headings.map((heading) => [heading.text.toLowerCase(), heading]));
    return segments.map((segment) => {
      const clean = segment.heading.replace(/^#+\s*/, "").trim();
      return { ...segment, clean, id: map.get(clean.toLowerCase())?.id };
    });
  }, [headings, segments]);

  if (headings.length === 0 && segments.length === 0) {
    return <p className="p-2 text-xs text-muted">No sections parsed yet.</p>;
  }

  return (
    <div className="space-y-0.5">
      {stamped.map((segment) => (
        <div key={`${segment.start}-${segment.clean}`} className={cn("flex items-center gap-2 rounded-lg px-2 py-1.5", segment.id === active && "bg-accent/10")}>
          <button onClick={() => onSeek(segment.start)} className="chip shrink-0 hover:text-accent">
            <Play className="h-2.5 w-2.5" />{formatClock(segment.start)}
          </button>
          <a
            href={`#${segment.id ?? ""}`}
            onClick={(event) => {
              if (segment.id) {
                event.preventDefault();
                document.getElementById(segment.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }
            }}
            className={cn("truncate text-[12px] hover:text-accent", segment.id === active ? "font-medium text-accent" : "text-ink/80")}
          >
            {segment.clean}
          </a>
        </div>
      ))}
    </div>
  );
}

function RecallTab({ rel, vault }: { rel: string; vault: string }) {
  const [cards, setCards] = useState<CardType[] | null>(null);
  const [quiz, setQuiz] = useState<QuizItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.cards(vault, 200), api.quiz(vault, 200)])
      .then(([cardData, quizData]) => {
        if (cancelled) return;
        setCards(cardData.cards.filter((card) => card.lesson === rel));
        setQuiz(quizData.items.filter((item) => item.lesson === rel));
      })
      .catch(() => {
        if (!cancelled) {
          setCards([]);
          setQuiz([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [rel, vault]);

  if (!cards && !quiz) return <div className="space-y-2 p-1">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)}</div>;

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
          <Brain className="h-3 w-3" /> Cards ({cards?.length ?? 0})
        </p>
        <div className="space-y-1.5">
          {(cards ?? []).slice(0, 6).map((card) => (
            <details key={card.id} className="rounded-lg border bg-bg/50 px-2.5 py-2">
              <summary className="cursor-pointer text-[12px] font-medium leading-snug">{card.front}</summary>
              <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{card.back}</p>
            </details>
          ))}
          {(cards ?? []).length === 0 ? <p className="text-[11px] text-muted">No cards yet — build them above.</p> : null}
        </div>
      </div>
      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
          <Sparkles className="h-3 w-3" /> Quiz ({quiz?.length ?? 0})
        </p>
        <div className="space-y-1.5">
          {(quiz ?? []).slice(0, 4).map((item) => (
            <details key={item.id} className="rounded-lg border bg-bg/50 px-2.5 py-2">
              <summary className="cursor-pointer text-[12px] font-medium leading-snug">{item.question}</summary>
              <p className="mt-1.5 text-[11px] leading-relaxed text-muted"><span className="text-good">Answer:</span> {item.answer}</p>
            </details>
          ))}
          {(quiz ?? []).length === 0 ? <p className="text-[11px] text-muted">No questions yet — build the quiz above.</p> : null}
        </div>
      </div>
      <Link to="/study" className="btn btn-soft btn-sm w-full">Open study session</Link>
    </div>
  );
}

function ExplainTab({ note, vault }: { note: Note; vault: string }) {
  const notify = useStore((state) => state.notify);
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);

  const grade = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setAnswer(null);
    try {
      const prompt = [
        `You are a strict but encouraging tutor. The student is explaining "${note.title}" in their own words.`,
        "Grade the explanation for accuracy and coverage against the course material.",
        "Respond in this shape:",
        "1) Verdict — one sentence, honest.",
        "2) What you got right — bullets.",
        "3) What is missing or wrong — bullets, each naming the concept.",
        "4) One probing question to close the gap.",
        "Keep it under 220 words. Do not restate the whole lesson.",
        "",
        "Student explanation:",
        '"""',
        text.trim(),
        '"""',
      ].join("\n");
      const result = await api.askCourse({ out: vault, question: prompt });
      setAnswer(result.answer);
      setCitations(result.citations ?? []);
    } catch (err) {
      notify("Explain-back failed", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-iris/25 bg-iris/5 p-3">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-iris">
          <GraduationCap className="h-3.5 w-3.5" /> Explain-back coach
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted">
          The Feynman test: explain it like the tutor knows nothing. You get a verdict,
          the gaps, and a question — grounded in this course.
        </p>
      </div>
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="In my own words, this lesson says…"
        className="input min-h-28 resize-y text-[12px]"
      />
      <Button size="sm" onClick={grade} loading={busy} disabled={!text.trim()} icon={<GraduationCap className="h-3.5 w-3.5" />} className="w-full">
        Grade my explanation
      </Button>
      <AnimatePresence>
        {answer ? (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border bg-bg/60 p-3">
            <Markdown markdown={answer} className="text-[12px] leading-relaxed" />
            {citations.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1">
                {citations.slice(0, 4).map((citation) => (
                  <Badge key={citation.n} tone="iris">[{citation.n}] {citation.title.slice(0, 22)}</Badge>
                ))}
              </div>
            ) : null}
          </motion.div>
        ) : busy ? (
          <div className="flex items-center gap-2 text-[11px] text-muted"><Loader2 className="h-3 w-3 animate-spin" /> reading your explanation…</div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function AskTab({ note, vault, source }: { note: Note; vault: string; source: string }) {
  const notify = useStore((state) => state.notify);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!question.trim()) return;
    const current = question.trim();
    setQuestion("");
    setTurns((prev) => [...prev, { role: "user", content: current }]);
    setBusy(true);
    try {
      const result = await api.ask({
        out: vault,
        rel: note.rel,
        source: source || undefined,
        question: current,
        history: turns.slice(-6),
      });
      setTurns((prev) => [...prev, { role: "assistant", content: result.answer }]);
    } catch (err) {
      notify("Question failed", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-300px)] min-h-[280px] flex-col">
      <div className="flex-1 space-y-2 overflow-y-auto pr-1">
        {turns.length === 0 ? (
          <div className="space-y-1.5">
            {["What is the core claim here?", "Explain the hardest step simply.", "What would the exam ask?"].map((suggestion) => (
              <button key={suggestion} onClick={() => setQuestion(suggestion)} className="w-full rounded-lg border bg-bg/50 px-2.5 py-2 text-left text-[11px] text-muted transition hover:border-accent/30 hover:text-ink">
                {suggestion}
              </button>
            ))}
          </div>
        ) : (
          turns.map((turn, index) => (
            <div key={index} className={cn("rounded-xl px-2.5 py-2 text-[12px]", turn.role === "user" ? "ml-6 bg-accent/10" : "mr-2 bg-bg/60")}>
              {turn.role === "assistant" ? <Markdown markdown={turn.content} className="text-[12px] leading-relaxed" /> : turn.content}
            </div>
          ))
        )}
        {busy ? (
          <div className="flex items-center gap-2 px-1 text-[11px] text-muted"><Loader2 className="h-3 w-3 animate-spin" /> thinking with this lesson…</div>
        ) : null}
      </div>
      <div className="mt-2 flex gap-1.5 border-t pt-2">
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          placeholder="Ask about this lesson…"
          className="h-9 text-[12px]"
        />
        <Button size="sm" onClick={send} disabled={!question.trim() || busy}>Ask</Button>
      </div>
    </div>
  );
}
