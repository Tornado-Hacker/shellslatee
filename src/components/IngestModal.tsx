import { AlertTriangle, Check, FolderOpen, Pause, Play, Square, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { bridge } from "@/lib/bridge";
import { celebrate } from "@/lib/celebrate";
import { useStore } from "@/lib/store";
import type { Job, ScanResult } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button, Input, Modal, Select } from "./ui";

const FINAL = new Set(["done", "failed", "stopped"]);

export function IngestModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const config = useStore((state) => state.config);
  const notify = useStore((state) => state.notify);
  const refresh = useStore((state) => state.refresh);
  const update = useStore((state) => state.update);
  const navigate = useNavigate();

  const [source, setSource] = useState(config?.source ?? "");
  const [course, setCourse] = useState("");
  const [jobs, setJobs] = useState(1);
  const [force, setForce] = useState(false);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const finishedRef = useRef<string | null>(null);

  useEffect(() => {
    setSource(config?.source ?? "");
  }, [config?.source]);

  useEffect(() => {
    if (!open || !source.trim()) {
      return;
    }
    let cancelled = false;
    setScanning(true);
    const timer = window.setTimeout(() => {
      api
        .scan(source.trim(), false)
        .then((data) => {
          if (!cancelled) setScan(data);
        })
        .catch(() => {
          if (!cancelled) setScan(null);
        })
        .finally(() => {
          if (!cancelled) setScanning(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, source]);

  useEffect(() => {
    if (!job || FINAL.has(job.status)) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      api
        .job(job.id)
        .then((next) => {
          if (cancelled) return;
          setJob(next);
          if (FINAL.has(next.status)) {
            window.clearInterval(timer);
            if (finishedRef.current !== next.id) {
              finishedRef.current = next.id;
              void refresh();
              if (next.written > 0) celebrate("finish");
              notify(
                next.status === "done" && next.written === 0
                  ? "Nothing new"
                  : next.status === "done"
                    ? "Vault built"
                    : next.status === "stopped"
                      ? "Run stopped"
                      : "Run finished with errors",
                `${next.written} written · ${next.skipped} skipped · ${next.failed} failed · $${next.usd.toFixed(4)}`,
                next.status === "done" ? "success" : next.status === "stopped" ? "info" : "error",
              );
            }
          }
        })
        .catch(() => undefined);
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status, notify, refresh]);

  if (!config) return null;

  const running = job ? !FINAL.has(job.status) : false;
  const progress = job && job.total > 0 ? Math.round((job.index / job.total) * 100) : 0;
  const counts = (scan?.items ?? []).reduce<Record<string, number>>((acc, item) => {
    acc[item.kind] = (acc[item.kind] ?? 0) + 1;
    return acc;
  }, {});

  const pick = async () => {
    const picked = await bridge.pickFolder("Choose the course folder (videos, slides, PDFs, audio)");
    if (!picked) return;
    setSource(picked);
    setScan(null);
    await update({ source: picked });
  };

  const start = async () => {
    if (!config.vault) {
      notify("No vault yet", "Set a notes folder in Settings first.", "error");
      return;
    }
    if (!source.trim()) return;
    setStarting(true);
    setScan(null);
    finishedRef.current = null;
    try {
      await update({ source: source.trim() });
      const started = await api.run({
        source: source.trim(),
        out: config.vault,
        provider: config.provider || undefined,
        model: config.model || undefined,
        course: course.trim() || undefined,
        jobs,
        force: force || undefined,
        max_cost: config.maxCostUsd && config.maxCostUsd > 0 ? config.maxCostUsd : undefined,
      });
      setJob(started);
      notify("Run started", `${started.total || "Scanning"} items queued`, "info");
    } catch (err) {
      notify("Could not start the run", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setStarting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Build the vault"
      description="Point at a course folder. Local transcription, notes, cards, quizzes — one run."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{running ? "Run in background" : "Close"}</Button>
          {job ? (
            <Button variant="outline" onClick={() => void refresh()} icon={<Check className="h-4 w-4" />}>
              Reload vault
            </Button>
          ) : null}
          <Button
            onClick={start}
            loading={starting}
            disabled={!source.trim() || !config.vault || running}
            icon={<Wand2 className="h-4 w-4" />}
          >
            {job && FINAL.has(job.status) ? "Run again" : "Start run"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px]">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted">Course folder</label>
            <div className="flex gap-2">
              <Input value={source} onChange={(event) => { setSource(event.target.value); setScan(null); }} placeholder="Folder of videos, slides, PDFs" className="font-mono text-[11px]" />
              <Button variant="outline" size="sm" onClick={pick} icon={<FolderOpen className="h-3.5 w-3.5" />}>Browse</Button>
            </div>
            <p className="text-[10px] text-muted">
              {scanning
                ? "scanning the folder…"
                : scan
                  ? `${scan.count} source${scan.count === 1 ? "" : "s"} · ${Object.entries(counts).map(([kind, count]) => `${count} ${kind}`).join(" · ")}`
                  : source
                    ? "nothing to scan yet"
                    : "pick a folder to see what will be processed"}
            </p>
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted">Course title</label>
            <Input value={course} onChange={(event) => setCourse(event.target.value)} placeholder="optional" />
            <label className="flex cursor-pointer items-center gap-1.5 pt-1 text-[11px] text-muted">
              <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} className="accent-[rgb(var(--accent))]" />
              Regenerate existing notes
            </label>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-xl border bg-bg/50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">Writes to</p>
            <p className="mt-0.5 truncate font-mono text-[11px]" title={config.vault}>{config.vault || "no vault — open Settings"}</p>
          </div>
          <div className="rounded-xl border bg-bg/50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">Model</p>
            <p className="mt-0.5 truncate text-[11px]">{config.provider} · {config.model || "default"}</p>
          </div>
          <div className="rounded-xl border bg-bg/50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">Parallel jobs</p>
            <Select value={String(jobs)} onChange={(event) => setJobs(Number(event.target.value))} className="mt-1 h-7 border-0 bg-transparent px-0 py-0 text-[11px]">
              <option value="1">1 — gentle on the CPU</option>
              <option value="2">2 — balanced</option>
              <option value="4">4 — fast machine</option>
            </Select>
          </div>
        </div>

        {!config.vault ? (
          <p className="flex items-center gap-2 rounded-xl border border-warn/30 bg-warn/5 px-3 py-2 text-[11px] text-warn">
            <AlertTriangle className="h-3.5 w-3.5" /> Set a vault folder in Settings before running.
          </p>
        ) : null}

        {job ? (
          <div className="space-y-3 rounded-xl border bg-bg/40 p-3.5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", running ? "animate-pulse bg-accent" : job.status === "done" ? "bg-good" : "bg-bad")} />
                <p className="text-[12px] font-medium capitalize">{job.status}{job.paused ? " · paused" : ""}</p>
              </div>
              <p className="text-[11px] text-muted">
                {job.index}/{job.total || "?"} · {job.written} written · {job.skipped} skipped · {job.failed} failed
              </p>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div
                className={cn("h-full rounded-full transition-[width] duration-500", job.status === "failed" ? "bg-bad" : "bg-accent")}
                style={{ width: `${job.total ? Math.max(3, progress) : 32}%` }}
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="truncate text-[11px] text-muted">
                {job.target ? `now: ${job.target}` : job.projection_usd !== null ? `projected $${job.projection_usd.toFixed(4)}` : "warming up"}
                {job.usd > 0 ? ` · spent $${job.usd.toFixed(4)}` : " · $0.0000 so far"}
              </p>
              {running ? (
                <div className="flex gap-1.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={job.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
                    onClick={async () => {
                      try {
                        setJob(job.paused ? await api.resume(job.id) : await api.pause(job.id));
                      } catch (err) {
                        notify("Control failed", err instanceof Error ? err.message : String(err), "error");
                      }
                    }}
                  >
                    {job.paused ? "Resume" : "Pause"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Square className="h-3 w-3" />}
                    onClick={async () => {
                      try {
                        setJob(await api.stop(job.id));
                      } catch (err) {
                        notify("Stop failed", err instanceof Error ? err.message : String(err), "error");
                      }
                    }}
                  >
                    Stop
                  </Button>
                </div>
              ) : null}
            </div>
            {job.log.length > 0 ? (
              <pre className="max-h-28 overflow-y-auto rounded-lg bg-bg p-2 font-mono text-[10px] leading-relaxed text-muted">
                {job.log.slice(-9).join("\n")}
              </pre>
            ) : null}
            {job.status === "done" || (job.status === "stopped" && job.written > 0) ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  onClose();
                  navigate("/library");
                }}
                icon={<Check className="h-3.5 w-3.5" />}
              >
                Open the new library
              </Button>
            ) : null}
          </div>
        ) : null}

        <p className="text-[10px] leading-relaxed text-muted">
          Runs in the local engine. Transcription is on this machine; only note prompts reach the model you chose.
          Existing notes are skipped unless you tick regenerate.
        </p>
      </div>
    </Modal>
  );
}
