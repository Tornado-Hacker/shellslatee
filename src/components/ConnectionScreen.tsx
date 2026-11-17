import { motion } from "framer-motion";
import { Check, Download, Loader2, RefreshCw, ServerCrash, Settings2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { bridge, isTauri } from "@/lib/bridge";
import { useStore } from "@/lib/store";
import type { PrereqReport } from "@/lib/types";
import { Button } from "./ui/primitives";

function Row({ label, detail, ok }: { label: string; detail: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border bg-bg/50 px-3.5 py-2.5">
      <div>
        <p className="text-[13px] font-medium">{label}</p>
        <p className="text-[11px] text-muted">{detail}</p>
      </div>
      <span
        className={
          ok
            ? "grid h-6 w-6 place-items-center rounded-full bg-good/15 text-good"
            : "grid h-6 w-6 place-items-center rounded-full bg-bad/15 text-bad"
        }
      >
        {ok ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
      </span>
    </div>
  );
}

export function ConnectionScreen() {
  const backend = useStore((state) => state.backend);
  const setBackend = useStore((state) => state.setBackend);
  const refresh = useStore((state) => state.refresh);
  const config = useStore((state) => state.config);
  const update = useStore((state) => state.update);
  const notify = useStore((state) => state.notify);
  const [busy, setBusy] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [autoInstall, setAutoInstall] = useState(true);
  const [prereqs, setPrereqs] = useState<PrereqReport | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const desktop = isTauri;

  useEffect(() => {
    if (!desktop) return;
    let alive = true;
    bridge
      .checkPrereqs()
      .then((report) => alive && setPrereqs(report))
      .catch(() => alive && setPrereqs(null));
    return () => {
      alive = false;
    };
  }, [desktop]);

  const missingPython = prereqs ? !prereqs.python : false;
  const missingEngine = prereqs ? !prereqs.engine : false;
  const anythingMissing = desktop && (missingPython || missingEngine);

  const retry = useCallback(async () => {
    setBusy(true);
    setProblem(null);
    try {
      const status = await bridge.restartBackend();
      setBackend(status);
      if (status.ready) {
        await refresh();
        notify("Engine is up", undefined, "success");
      } else {
        setProblem(status.error ?? "The engine still isn't responding.");
      }
    } finally {
      setBusy(false);
    }
  }, [notify, refresh, setBackend]);

  // The shell already restarts a crashed engine; this keeps the screen honest
  // while it comes back, so nobody has to mash "try again".
  useEffect(() => {
    if (!desktop || backend.ready || anythingMissing || installing) return;
    if (!prereqs?.ready) return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled || busy) return;
      try {
        const status = await bridge.backendStatus();
        if (cancelled) return;
        if (status.ready) {
          setBackend(status);
          await refresh();
        }
      } catch {
        /* the supervisor is still working; try again next tick */
      }
    };
    const id = window.setInterval(() => {
      void tick();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [anythingMissing, backend.ready, busy, desktop, installing, prereqs?.ready, refresh, setBackend]);

  const install = async () => {
    setInstalling(true);
    setProblem(null);
    try {
      await bridge.installPrereqs();
      const report = await bridge.checkPrereqs();
      setPrereqs(report);
      const status = await bridge.restartBackend();
      setBackend(status);
      if (status.ready) {
        await refresh();
        notify("Everything installed", "The local engine is running.", "success");
      } else {
        setProblem(status.error ?? "Installed, but the engine still isn't responding.");
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setInstalling(false);
    }
  };

  return (
    <div className="grain relative grid h-screen place-items-center overflow-hidden bg-bg p-6">
      <div className="pointer-events-none absolute left-1/2 top-1/3 h-[420px] w-[420px] -translate-x-1/2 rounded-full bg-accent/15 blur-[120px]" />
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative w-full max-w-lg rounded-xl3 border bg-surface/85 p-7 shadow-lift backdrop-blur"
      >
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-2xl bg-warn/12 text-warn">
            <ServerCrash className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">
              {anythingMissing ? "One quick setup" : "The local engine is taking a nap"}
            </h1>
            <p className="text-xs text-muted">
              {anythingMissing
                ? "Shellslatee needs two small pieces before it can read your vault."
                : "Shellslatee runs a tiny Python server to read your vault."}
            </p>
          </div>
        </div>

        {desktop && prereqs ? (
          <div className="mt-5 space-y-2">
            <Row
              label="Python"
              detail={prereqs.python ? `Python ${prereqs.python} ready` : "Not found — 3.10 or newer"}
              ok={Boolean(prereqs.python)}
            />
            <Row
              label="Local engine"
              detail={prereqs.engine ? "Installed" : prereqs.wheel ? "Bundled — installs in seconds" : "Missing from this build"}
              ok={prereqs.engine}
            />
          </div>
        ) : null}

        {problem ? (
          <div className="mt-4 rounded-xl border bg-bg/60 p-3.5">
            <p className="text-[11px] uppercase tracking-wider text-muted">Last error</p>
            <p className="mt-1 break-words font-mono text-[11px] leading-relaxed text-bad/90">{problem}</p>
          </div>
        ) : null}

        {anythingMissing ? (
          <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-xl border bg-bg/40 p-3.5">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-accent"
              checked={autoInstall}
              onChange={(event) => setAutoInstall(event.target.checked)}
              disabled={installing}
            />
            <span className="text-[12.5px] leading-relaxed text-muted">
              <span className="font-medium text-ink">Install the missing software for me.</span>{" "}
              Downloads the official Python installer if needed, then installs the bundled engine — no admin
              rights and no terminal.
            </span>
          </label>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => update({ onboarded: false })}
            icon={<Settings2 className="h-4 w-4" />}
          >
            Setup
          </Button>
          {anythingMissing ? (
            <Button
              onClick={install}
              disabled={!autoInstall || installing}
              loading={installing}
              icon={<Download className="h-4 w-4" />}
            >
              {missingPython ? "Download & install" : "Install engine"}
            </Button>
          ) : (
            <Button onClick={retry} loading={busy} icon={<RefreshCw className="h-4 w-4" />}>
              Try again
            </Button>
          )}
        </div>

        {installing ? (
          <p className="mt-3 flex items-center justify-end gap-2 text-[11px] text-muted">
            <Loader2 className="h-3 w-3 animate-spin" /> installing, this takes about a minute…
          </p>
        ) : null}

        {desktop && prereqs?.ready && !backend.ready && !anythingMissing ? (
          <p className="mt-3 flex items-center gap-2 text-[11px] text-muted">
            <Loader2 className="h-3 w-3 animate-spin" /> Recovering the engine automatically…
          </p>
        ) : null}

        {desktop && prereqs?.ready && !backend.ready ? (
          <p className="mt-3 text-[11px] text-muted">
            Vault: <span className="font-mono text-[11px] text-ink/80">{config?.vault || "not set"}</span>
          </p>
        ) : null}

        {!desktop ? (
          <p className="mt-4 text-[11px] leading-relaxed text-muted">
            Browser preview — installing is only available in the desktop app.
          </p>
        ) : null}
      </motion.div>
    </div>
  );
}
