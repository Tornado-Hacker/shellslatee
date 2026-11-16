import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUpRight,
  BookOpen,
  Compass,
  CornerDownLeft,
  Layers,
  MessageSquare,
  RefreshCw,
  Sparkles,
  Wand2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Markdown } from "@/components/Markdown";
import { Button, Card, EmptyState, SectionHeader, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { Citation } from "@/lib/types";
import { cn, formatClock } from "@/lib/utils";

type Turn = {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  meta?: { provider?: string; model?: string; tokens?: { in: number; out: number } };
};

let turnSeq = 1;

export function AskPage() {
  const config = useStore((state) => state.config);
  const vault = useStore((state) => state.vault);
  const notify = useStore((state) => state.notify);
  const navigate = useNavigate();

  const [scope, setScope] = useState<string>("course");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const lessons = vault?.lessons ?? [];
  const concepts = vault?.concepts ?? [];
  const suggestions = useMemo(() => {
    const picks = concepts.slice(0, 3).map((concept) => `Explain ${concept.name} and where it shows up in the course.`);
    const lesson = lessons[0];
    return [
      ...picks,
      "What are the five ideas most likely to be on the exam?",
      lesson ? `Summarise "${lesson.title}" in three bullets.` : "Give me a study plan for this vault.",
    ].slice(0, 5);
  }, [concepts, lessons]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  if (!config?.vault) {
    return (
      <EmptyState
        icon={<MessageSquare className="h-6 w-6" />}
        title="The tutor needs a vault"
        body="Point Shellslatee at your notes in Settings and the whole course becomes the context."
        action={<Link to="/settings" className="btn btn-primary btn-sm">Open settings</Link>}
      />
    );
  }

  const send = async (text?: string) => {
    const asked = (text ?? question).trim();
    if (!asked || busy) return;
    setQuestion("");
    setTurns((prev) => [...prev, { id: turnSeq++, role: "user", content: asked }]);
    setBusy(true);
    try {
      if (scope === "course") {
        const history = turns
          .slice(-4)
          .map((turn) => `${turn.role === "user" ? "Student" : "Tutor"}: ${turn.content}`)
          .join("\n");
        const prompt = history ? `Prior conversation:\n${history}\n\nNew question: ${asked}` : asked;
        const result = await api.askCourse({
          out: config.vault,
          question: prompt,
          provider: config.provider || undefined,
          model: config.model || undefined,
        });
        setTurns((prev) => [
          ...prev,
          {
            id: turnSeq++,
            role: "assistant",
            content: result.answer,
            citations: result.citations,
            meta: { provider: result.provider, model: result.model, tokens: result.tokens },
          },
        ]);
      } else {
        const result = await api.ask({
          out: config.vault,
          rel: scope,
          source: config.source || undefined,
          question: asked,
          provider: config.provider || undefined,
          model: config.model || undefined,
          history: turns.slice(-4).map((turn) => ({ role: turn.role, content: turn.content })),
        });
        setTurns((prev) => [
          ...prev,
          { id: turnSeq++, role: "assistant", content: result.answer, meta: { provider: result.provider, model: result.model, tokens: result.tokens } },
        ]);
      }
    } catch (err) {
      notify("No answer", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setBusy(false);
      window.setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const reset = () => {
    setTurns([]);
    setQuestion("");
    inputRef.current?.focus();
  };

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex h-[calc(100vh-8.5rem)] flex-col gap-4">
      <SectionHeader
        title="Ask the course"
        subtitle="Answers grounded in your own notes, with citations back to the exact line."
        action={
          turns.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={reset} icon={<RefreshCw className="h-3.5 w-3.5" />}>New thread</Button>
          ) : undefined
        }
      />

      {turns.length === 0 ? (
        <div className="grid flex-1 place-items-center overflow-y-auto">
          <div className="w-full max-w-xl space-y-5">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-accent/20 to-iris/20">
                <Compass className="h-6 w-6 text-accent" />
              </div>
              <div>
                <p className="font-display text-2xl">Your course, at the mouth of the fridge.</p>
                <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-muted">
                  Ask anything — it reads the vault, quotes the lecture, and tells you where it got it.
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => void send(suggestion)}
                  className="group flex items-center gap-3 rounded-2xl border bg-surface/50 px-4 py-3 text-left text-[13px] transition hover:border-accent/35 hover:bg-accent/5"
                >
                  <Sparkles className="h-4 w-4 shrink-0 text-iris" />
                  <span className="flex-1">{suggestion}</span>
                  <ArrowUpRight className="h-4 w-4 shrink-0 text-muted opacity-0 transition group-hover:opacity-100" />
                </button>
              ))}
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                { icon: BookOpen, label: `${lessons.length} lessons` },
                { icon: Layers, label: `${concepts.length} concepts` },
                { icon: Wand2, label: "cited answers" },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border bg-surface/40 px-2 py-2.5">
                  <item.icon className="mx-auto h-3.5 w-3.5 text-muted" />
                  <p className="mt-1 text-[10px] text-muted">{item.label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto pr-1">
          <AnimatePresence initial={false}>
            {turns.map((turn) => (
              <motion.div
                key={turn.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn("flex", turn.role === "user" ? "justify-end" : "justify-start")}
              >
                {turn.role === "user" ? (
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent/12 px-4 py-2.5 text-[13px] leading-relaxed">{turn.content}</div>
                ) : (
                  <Card className="w-full max-w-[92%] p-4 md:p-5">
                    <Markdown markdown={turn.content} className="text-[13.5px]" />
                    {turn.citations && turn.citations.length > 0 ? (
                      <div className="mt-3 space-y-1.5 border-t pt-3">
                        <p className="text-[10px] uppercase tracking-wider text-muted">Sources</p>
                        <div className="flex flex-wrap gap-1.5">
                          {turn.citations.map((citation) => (
                            <button
                              key={`${citation.n}-${citation.rel}`}
                              onClick={() => navigate(`/note/${encodeURIComponent(citation.rel)}`)}
                              className="chip max-w-full hover:border-accent/40 hover:text-accent"
                              title={citation.snippet}
                            >
                              <span className="font-semibold">[{citation.n}]</span>
                              <span className="truncate">{citation.title}</span>
                              {citation.start !== null ? <span className="text-muted">{formatClock(citation.start)}</span> : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {turn.meta ? (
                      <p className="mt-3 text-[10px] text-muted">
                        {turn.meta.provider} · {turn.meta.model}
                        {turn.meta.tokens ? ` · ${turn.meta.tokens.in}→${turn.meta.tokens.out} tokens` : ""}
                      </p>
                    ) : null}
                  </Card>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
          {busy ? (
            <div className="flex items-center gap-2.5 px-1 text-[12px] text-muted">
              <Spinner className="h-3.5 w-3.5" />
              reading the vault and writing an answer…
            </div>
          ) : null}
          <div ref={endRef} />
        </div>
      )}

      <div className="shrink-0 space-y-2">
        <div className="flex items-center gap-2">
          <Select value={scope} onChange={(event) => setScope(event.target.value)} className="h-8 w-auto max-w-[240px] py-0 text-[11px]">
            <option value="course">Whole course</option>
            {lessons.map((lesson) => (
              <option key={lesson.rel} value={lesson.rel}>{lesson.title}</option>
            ))}
          </Select>
          <span className="text-[10px] text-muted">{scope === "course" ? "searches every lesson" : "this lesson only"}</span>
        </div>
        <div className="flex items-end gap-2 rounded-2xl border bg-surface/60 p-2">
          <textarea
            ref={inputRef}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder="Ask anything about the course…"
            rows={1}
            className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[13px] outline-none placeholder:text-muted"
          />
          <Button size="sm" onClick={() => void send()} disabled={!question.trim() || busy} icon={<CornerDownLeft className="h-3.5 w-3.5" />}>
            Ask
          </Button>
        </div>
        <p className="text-center text-[10px] text-muted">Enter to send · Shift+Enter for a new line · answers cite the vault</p>
      </div>
    </motion.div>
  );
}
