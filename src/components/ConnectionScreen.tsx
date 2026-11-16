import { motion } from "framer-motion";
import { Loader2, RefreshCw, ServerCrash, Settings2, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { bridge } from "@/lib/bridge";
import { useStore } from "@/lib/store";
import { Button } from "./ui/primitives";

export function ConnectionScreen() {
  const backend = useStore((state) => state.backend);
  const setBackend = useStore((state) => state.setBackend);
  const refresh = useStore((state) => state.refresh);
  const config = useStore((state) => state.config);
  const update = useStore((state) => state.update);
  const notify = useStore((state) => state.notify);
  const [busy, setBusy] = useState(false);

  const retry = async () => {
    setBusy(true);
    try {
      const status = await bridge.restartBackend();
      setBackend(status);
      if (status.ready) {
        await refresh();
        notify("Engine is up", undefined, "success");
      } else {
        notify("Still offline", status.error ?? "Check that Python and the shellslatee engine are installed.", "error");
      }
    } finally {
      setBusy(false);
    }
  };

  const platform = bridge.platform();

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
            <h1 className="text-lg font-semibold">The local engine is taking a nap</h1>
            <p className="text-xs text-muted">Shellslatee runs a tiny Python server to read your vault.</p>
          </div>
        </div>

        <div className="mt-5 rounded-xl border bg-bg/60 p-3.5">
          <p className="text-[11px] uppercase tracking-wider text-muted">Last error</p>
          <p className="mt-1 break-words font-mono text-[11px] leading-relaxed text-bad/90">
            {backend.error || "No response from the engine."}
          </p>
        </div>

        <div className="mt-5 space-y-2 text-[13px] text-muted">
          <p className="flex items-center gap-2 font-medium text-ink">
            <TerminalSquare className="h-4 w-4 text-accent" /> One-time check
          </p>
          <p>
            Install the engine once{platform === "windows" ? " (PowerShell)" : ""}:
          </p>
          <pre className="overflow-x-auto rounded-xl border bg-bg p-3 font-mono text-[11px] text-ink/85">
{platform === "windows"
  ? "pip install --user shellslatee-engine\n# dev: pip install -e C:\\path\\to\\shellslatee-engine"
  : "pip install --user shellslatee-engine\n# dev: pip install -e /path/to/shellslatee-engine"}
          </pre>
          <p className="text-[12px]">
            Vault: <span className="font-mono text-[11px] text-ink/80">{config?.vault || "not set"}</span>
          </p>
        </div>

        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => update({ onboarded: false })}
            icon={<Settings2 className="h-4 w-4" />}
          >
            Re-run setup
          </Button>
          <Button onClick={retry} loading={busy} icon={<RefreshCw className="h-4 w-4" />}>
            Try again
          </Button>
        </div>
        {busy ? (
          <p className="mt-3 flex items-center justify-end gap-2 text-[11px] text-muted">
            <Loader2 className="h-3 w-3 animate-spin" /> restarting engine…
          </p>
        ) : null}
      </motion.div>
    </div>
  );
}
