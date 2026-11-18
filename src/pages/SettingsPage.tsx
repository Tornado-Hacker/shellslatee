import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  Cpu,
  Download,
  Eye,
  FolderOpen,
  KeyRound,
  Moon,
  Palette,
  RefreshCw,
  Server,
  Sparkles,
  Sun,
  Trash2,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, Input, SectionHeader, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { bridge } from "@/lib/bridge";
import { riseItem, stagger } from "@/lib/motion";
import { useStore } from "@/lib/store";
import type { Accent, AsrStatus, Provider, Theme } from "@/lib/types";
import { cn } from "@/lib/utils";

const accents: { id: Accent; label: string; color: string }[] = [
  { id: "ember", label: "Ember", color: "rgb(255 122 69)" },
  { id: "iris", label: "Iris", color: "rgb(139 123 255)" },
  { id: "jade", label: "Jade", color: "rgb(74 190 138)" },
  { id: "cobalt", label: "Cobalt", color: "rgb(77 141 255)" },
];

export function SettingsPage() {
  const config = useStore((state) => state.config);
  const backend = useStore((state) => state.backend);
  const update = useStore((state) => state.update);
  const setBackend = useStore((state) => state.setBackend);
  const refresh = useStore((state) => state.refresh);
  const notify = useStore((state) => state.notify);
  const reset = useStore((state) => state.reset);

  const [providers, setProviders] = useState<Provider[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(true);
  const [key, setKey] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [asr, setAsr] = useState<AsrStatus | null>(null);
  const [asrBusy, setAsrBusy] = useState(false);
  const [asrLine, setAsrLine] = useState("");
  const [check, setCheck] = useState<{ ok: boolean; detail: string } | null>(null);
  const [model, setModel] = useState(config?.model ?? "");
  const [restarting, setRestarting] = useState(false);
  const [examTitle, setExamTitle] = useState(config?.examTitle ?? "");
  const [examDate, setExamDate] = useState(config?.examDate ?? "");
  const [dailyMinutes, setDailyMinutes] = useState(config?.dailyMinutes ?? 25);

  useEffect(() => {
    if (!backend.ready) {
      setLoadingProviders(false);
      return;
    }
    api
      .providers()
      .then((data) => setProviders(data.presets))
      .catch(() => setProviders([]))
      .finally(() => setLoadingProviders(false));
  }, [backend.ready]);

  useEffect(() => {
    setModel(config?.model ?? "");
  }, [config?.model]);

  useEffect(() => {
    if (!backend.ready) return;
    let live = true;
    api
      .asrStatus()
      .then((report) => {
        if (live) setAsr(report);
      })
      .catch(() => {
        if (live) setAsr(null);
      });
    return () => {
      live = false;
    };
  }, [backend.ready]);

  if (!config) return null;

  const selectedProvider = providers.find((provider) => provider.name === config.provider);

  const recheckEngine = async () => {
    setAsrBusy(true);
    try {
      setAsr(await api.asrStatus());
    } catch (err) {
      notify("Engine check failed", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setAsrBusy(false);
    }
  };

  const setupAsr = async () => {
    setAsrBusy(true);
    setAsrLine("starting…");
    try {
      let job = await api.asrProvision("tiny.en");
      for (let tick = 0; tick < 900; tick += 1) {
        job = await api.job(job.id);
        const tail = job.log?.[job.log.length - 1];
        if (tail) setAsrLine(tail.replace(/^\[asr\]\s*/, ""));
        if (job.status !== "running") break;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      if (job.status === "failed") {
        throw new Error(job.log?.[job.log.length - 1] ?? "provisioning failed");
      }
      const applied = await api.asrApply();
      setAsr(await api.asrStatus());
      notify(
        applied.ready ? "Transcription ready" : "Transcription partly installed",
        applied.ready
          ? "ffmpeg, the whisper wrapper and a model are in place."
          : "Re-check below to see what is still missing.",
        applied.ready ? "success" : "info",
      );
    } catch (err) {
      notify("Setup failed", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setAsrBusy(false);
      setAsrLine("");
    }
  };

  const pickVault = async () => {
    const picked = await bridge.pickFolder("Choose the folder that holds generated notes");
    if (!picked) return;
    await update({ vault: picked });
    notify("Vault set", picked, "success");
  };

  const pickSource = async () => {
    const picked = await bridge.pickFolder("Choose the source folder (videos, slides, PDFs)");
    if (!picked) return;
    await update({ source: picked });
    notify("Source set", picked, "success");
  };

  const saveKey = async () => {
    if (!key.trim()) return;
    setKeyBusy(true);
    setCheck(null);
    try {
      const verdict = await bridge.verifyApiKey(config.provider, key.trim());
      setCheck(verdict);
      await bridge.saveApiKey(config.provider, key.trim());
      const next = await bridge.restartBackend();
      setBackend(next);
      if (next.ready) {
        await refresh();
        api.providers().then((data) => setProviders(data.presets)).catch(() => undefined);
      }
      setKey("");
      notify(
        next.ready ? "Key saved and engine restarted" : "Key saved — engine still starting",
        verdict.ok ? verdict.detail : "Saved, but the live check did not pass. Verify the key when you're back online.",
        verdict.ok && next.ready ? "success" : "info",
      );
    } catch (err) {
      notify("Could not save key", err instanceof Error ? err.message : String(err), "error");
    } finally {
      setKeyBusy(false);
    }
  };

  const testKey = async () => {
    if (!key.trim()) return;
    setChecking(true);
    setCheck(null);
    try {
      setCheck(await bridge.verifyApiKey(config.provider, key.trim()));
    } catch (err) {
      setCheck({ ok: false, detail: err instanceof Error ? err.message : String(err) });
    } finally {
      setChecking(false);
    }
  };

  const restartEngine = async () => {
    setRestarting(true);
    try {
      const next = await bridge.restartBackend();
      setBackend(next);
      if (next.ready) {
        await refresh();
        notify("Engine restarted", next.base ?? undefined, "success");
      } else {
        notify("Engine did not come back", next.error ?? undefined, "error");
      }
    } finally {
      setRestarting(false);
    }
  };

  return (
    <motion.div variants={stagger} initial="initial" animate="enter" className="space-y-7 pb-10">
      <motion.div variants={riseItem}>
        <SectionHeader title="Settings" subtitle="Your keys, your folders, your machine. Nothing routes through us." />
      </motion.div>

      <motion.div variants={riseItem}>
        <Card className="overflow-hidden p-0">
          <div className="flex items-center justify-between gap-3 border-b p-4">
            <div className="flex items-center gap-2.5">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 text-accent"><KeyRound className="h-4 w-4" /></div>
              <div>
                <p className="text-[13px] font-semibold">AI provider &amp; key</p>
                <p className="text-[11px] text-muted">Bring your own key. Stored locally, never sent anywhere but the provider.</p>
              </div>
            </div>
            {selectedProvider ? (
              <Badge tone={selectedProvider.ready ? "good" : "warn"}>{selectedProvider.ready ? "key detected" : "no key"}</Badge>
            ) : null}
          </div>

          <div className="grid gap-4 p-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted">Provider</label>
              {loadingProviders ? (
                <div className="input flex items-center gap-2 text-muted"><Spinner className="h-3.5 w-3.5" /> checking providers…</div>
              ) : (
                <Select
                  value={config.provider}
                  onChange={(event) => {
                    const provider = providers.find((item) => item.name === event.target.value);
                    void update({ provider: event.target.value, model: provider?.default_model ?? model });
                  }}
                >
                  {providers.length === 0 ? <option value={config.provider}>{config.provider}</option> : null}
                  {providers.map((provider) => (
                    <option key={provider.name} value={provider.name}>
                      {provider.name} {provider.ready ? "· ready" : ""}
                    </option>
                  ))}
                </Select>
              )}
              {selectedProvider ? (
                <p className="truncate text-[10px] text-muted">{selectedProvider.base_url} — {selectedProvider.detail}</p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted">Model override</label>
              <Input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                onBlur={() => void update({ model })}
                placeholder={selectedProvider?.default_model ?? "provider default"}
              />
              <p className="text-[10px] text-muted">Leave blank to use the provider's default.</p>
            </div>

            <div className="space-y-1.5 md:col-span-2">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted">
                {config.provider} API key
              </label>
              <div className="flex gap-2">
                <Input
                  type="password"
                  value={key}
                  onChange={(event) => {
                    setKey(event.target.value);
                    setCheck(null);
                  }}
                  placeholder="paste your key — it never leaves this machine"
                  autoComplete="off"
                  spellCheck={false}
                />
                <Button variant="outline" onClick={testKey} loading={checking} disabled={!key.trim()} icon={<Eye className="h-3.5 w-3.5" />}>
                  Test
                </Button>
                <Button onClick={saveKey} loading={keyBusy} disabled={!key.trim()} icon={<Check className="h-3.5 w-3.5" />}>
                  Save
                </Button>
              </div>
              {check ? (
                <p className={cn("flex items-center gap-1.5 text-[11px]", check.ok ? "text-good" : "text-bad")}>
                  {check.ok ? <Check className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                  {check.detail}
                </p>
              ) : (
                <p className="text-[10px] text-muted">Saving restarts the local engine so the key takes effect.</p>
              )}
              <button
                onClick={async () => {
                  await bridge.clearApiKey(config.provider);
                  const next = await bridge.restartBackend();
                  setBackend(next);
                  api.providers().then((data) => setProviders(data.presets)).catch(() => undefined);
                  notify("Key cleared", `${config.provider} key removed from this machine`, "info");
                }}
                className="text-[10px] text-muted underline-offset-2 hover:text-bad hover:underline"
              >
                Remove stored key
              </button>
            </div>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={riseItem}>
        <Card className="p-4">
          <div className="mb-4 flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-iris/10 text-iris"><FolderOpen className="h-4 w-4" /></div>
            <div>
              <p className="text-[13px] font-semibold">Folders</p>
              <p className="text-[11px] text-muted">Vault = generated notes. Source = lectures, slides, PDFs.</p>
            </div>
          </div>
          <div className="space-y-3">
            <FolderRow label="Vault" value={config.vault} onPick={pickVault} onOpen={() => config.vault && bridge.openPath(config.vault)} />
            <FolderRow label="Source" value={config.source} onPick={pickSource} onOpen={() => config.source && bridge.openPath(config.source)} />
          </div>
          <div className="mt-3 flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                const suggestion = await bridge.defaultVault();
                if (suggestion) {
                  await update({ vault: suggestion });
                  notify("Vault set", suggestion, "success");
                } else {
                  notify("No default folder found", "Pick one manually — usually your notes directory.", "info");
                }
              }}
            >
              Use default vault
            </Button>
            <Button variant="ghost" size="sm" onClick={() => refresh()} icon={<RefreshCw className="h-3.5 w-3.5" />}>
              Reload vault
            </Button>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={riseItem}>
        <Card className="p-4">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-iris/10 text-iris"><Cpu className="h-4 w-4" /></div>
              <div>
                <p className="text-[13px] font-semibold">Transcription engine</p>
                <p className="text-[11px] text-muted">
                  Videos need ffmpeg, ffprobe, a whisper binary and a model. Slides and PDFs do not.
                </p>
              </div>
            </div>
            {asr && (
              <Badge tone={asr.ready ? "good" : "warn"}>
                {asr.ready ? "ready" : "needs setup"}
              </Badge>
            )}
          </div>
          {!asr ? (
            <p className="text-[12px] text-muted">
              {backend.ready ? "Checking the local engine…" : "Waiting for the engine to start."}
            </p>
          ) : (
            <div className="space-y-1.5">
              {asr.checks.map((row) => (
                <div key={row.name} className="flex items-start gap-2 text-[12px]">
                  <Badge tone={row.ok ? "good" : "warn"} className="mt-0.5 shrink-0">
                    {row.ok ? "ok" : "miss"}
                  </Badge>
                  <span className="w-[7.5rem] shrink-0 font-medium">{row.name}</span>
                  <span className="min-w-0 break-words text-muted">{row.detail}</span>
                </div>
              ))}
              {asr.ready && (
                <p className="pt-2 text-[11px] text-muted">
                  Installed in <code className="rounded bg-line/40 px-1 py-0.5">{asr.target}</code>
                </p>
              )}
              {!asr.ready && (
                <p className="pt-2 text-[11px] text-muted">
                  Setup downloads a static ffmpeg (~40 MB), a ggml-tiny.en model (~75 MB) and a
                  faster-whisper wrapper. One time, no terminal needed.
                </p>
              )}
              {asrLine && (
                <p className="truncate pt-1 font-mono text-[10.5px] text-muted">{asrLine}</p>
              )}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {asr && !asr.ready && (
              <Button
                size="sm"
                disabled={asrBusy || !backend.ready}
                onClick={() => void setupAsr()}
                icon={<Download className={cn("h-3.5 w-3.5", asrBusy && "animate-pulse")} />}
              >
                {asrBusy ? "Setting up…" : "Set up transcription"}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={asrBusy}
              onClick={() => void recheckEngine()}
              icon={<RefreshCw className={cn("h-3.5 w-3.5", asrBusy && "animate-spin")} />}
            >
              Re-check
            </Button>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={riseItem} className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <div className="mb-3 flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 text-accent"><Palette className="h-4 w-4" /></div>
            <p className="text-[13px] font-semibold">Appearance</p>
          </div>
          <div className="space-y-3">
            <div>
              <p className="mb-1.5 text-[11px] uppercase tracking-wider text-muted">Theme</p>
              <div className="flex gap-2">
                {(
                  [
                    { id: "dark", label: "Dark", icon: Moon },
                    { id: "light", label: "Light", icon: Sun },
                  ] as { id: Theme; label: string; icon: typeof Moon }[]
                ).map((item) => (
                  <button
                    key={item.id}
                    onClick={() => void update({ theme: item.id })}
                    className={cn(
                      "flex flex-1 items-center justify-center gap-1.5 rounded-xl border py-2 text-[12px] transition",
                      config.theme === item.id ? "border-accent/45 bg-accent/10 text-accent" : "text-muted hover:text-ink",
                    )}
                  >
                    <item.icon className="h-3.5 w-3.5" /> {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-1.5 text-[11px] uppercase tracking-wider text-muted">Accent</p>
              <div className="flex gap-2">
                {accents.map((accent) => (
                  <button
                    key={accent.id}
                    onClick={() => void update({ accent: accent.id })}
                    className={cn(
                      "flex flex-1 items-center justify-center gap-1.5 rounded-xl border py-2 text-[11px] transition",
                      config.accent === accent.id ? "border-accent/45 bg-accent/10" : "text-muted hover:text-ink",
                    )}
                  >
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: accent.color }} />
                    {accent.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </Card>

        <Card className="p-4">
          <div className="mb-3 flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-good/10 text-good"><Zap className="h-4 w-4" /></div>
            <p className="text-[13px] font-semibold">Study defaults</p>
          </div>
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-[11px] uppercase tracking-wider text-muted">Exam</label>
              <Input
                value={examTitle}
                onChange={(event) => setExamTitle(event.target.value)}
                onBlur={() => void update({ examTitle })}
                placeholder="e.g. Networks midterm"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-[11px] uppercase tracking-wider text-muted">Date</label>
                <Input
                  type="date"
                  value={examDate}
                  onChange={(event) => setExamDate(event.target.value)}
                  onBlur={() => void update({ examDate })}
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] uppercase tracking-wider text-muted">Minutes / day</label>
                <Input
                  type="number"
                  min={5}
                  max={480}
                  value={dailyMinutes}
                  onChange={(event) => setDailyMinutes(Number(event.target.value))}
                  onBlur={() => void update({ dailyMinutes: Math.max(5, Math.min(480, dailyMinutes || 25)) })}
                />
              </div>
            </div>
            <p className="text-[10px] leading-relaxed text-muted">The home cockpit uses these to size today's plan.</p>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={riseItem}>
        <Card className="p-4">
          <div className="mb-3 flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 text-accent"><Server className="h-4 w-4" /></div>
            <div>
              <p className="text-[13px] font-semibold">Local engine</p>
              <p className="text-[11px] text-muted">The Python backend that reads files, builds notes, and talks to your provider.</p>
            </div>
            <Badge tone={backend.ready ? "good" : "bad"} className="ml-auto">{backend.ready ? "running" : "stopped"}</Badge>
          </div>
          <div className="grid gap-2 rounded-xl bg-bg/60 p-3 font-mono text-[11px]">
            <div className="flex justify-between gap-3"><span className="text-muted">base</span><span className="truncate">{backend.base ?? "—"}</span></div>
            <div className="flex justify-between gap-3"><span className="text-muted">version</span><span>{backend.version ?? "—"}</span></div>
            <div className="flex justify-between gap-3"><span className="text-muted">error</span><span className={cn("truncate", backend.error && "text-bad")}>{backend.error ?? "none"}</span></div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" loading={restarting} onClick={restartEngine} icon={<RefreshCw className="h-3.5 w-3.5" />}>
              Restart engine
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void refresh()} icon={<Cpu className="h-3.5 w-3.5" />}>
              Re-probe vault
            </Button>
          </div>
        </Card>
      </motion.div>

      <motion.div variants={riseItem}>
        <Card className="border-bad/25 p-4">
          <div className="mb-2 flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-bad/10 text-bad"><AlertTriangle className="h-4 w-4" /></div>
            <p className="text-[13px] font-semibold">Reset &amp; removal</p>
          </div>
          <p className="mb-3 text-[11px] leading-relaxed text-muted">
            Re-run setup or go back to the welcome screen. Your notes and API keys on disk are never deleted from here.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              icon={<Sparkles className="h-3.5 w-3.5" />}
              onClick={() => void update({ onboarded: false })}
            >
              Re-run setup
            </Button>
            <Button
              variant="danger"
              size="sm"
              icon={<Trash2 className="h-3.5 w-3.5" />}
              onClick={() => {
                if (window.confirm("Clear the app's saved settings (not your notes) and return to the welcome screen?")) {
                  void reset();
                }
              }}
            >
              Clear app settings
            </Button>
          </div>
        </Card>
      </motion.div>
    </motion.div>
  );
}

function FolderRow({ label, value, onPick, onOpen }: { label: string; value: string; onPick: () => void; onOpen: () => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-[11px] uppercase tracking-wider text-muted">{label}</span>
      <div className={cn("flex-1 truncate rounded-xl border bg-bg/50 px-3 py-2 text-[12px]", !value && "text-muted")}>
        {value || "not set"}
      </div>
      <Button variant="outline" size="sm" onClick={onPick}>Choose</Button>
      <Button variant="ghost" size="sm" disabled={!value} onClick={onOpen} icon={<FolderOpen className="h-3.5 w-3.5" />}>Open</Button>
    </div>
  );
}
