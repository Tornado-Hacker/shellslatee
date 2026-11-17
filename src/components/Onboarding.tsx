import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Eye,
  EyeOff,
  FolderOpen,
  KeyRound,
  Loader2,
  Scissors,
  ShieldCheck,
  Sparkles,
  Wand2,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { bridge } from "@/lib/bridge";
import { celebrate } from "@/lib/celebrate";
import { slideStep } from "@/lib/motion";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Button, Input } from "./ui/primitives";

const PROVIDERS = [
  {
    name: "aikey",
    label: "AI Key",
    model: "deepseek-v4.1-flash:free",
    blurb: "Free tier, good quality. The default.",
    keyHint: "your AI key",
    needsKey: true,
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    model: "meta-llama/llama-3.3-70b-instruct:free",
    blurb: "One key, dozens of models, free options.",
    keyHint: "openrouter.ai/keys",
    needsKey: true,
  },
  {
    name: "openai",
    label: "OpenAI",
    model: "gpt-4o-mini",
    blurb: "Reliable and fast. Paid per token.",
    keyHint: "platform.openai.com",
    needsKey: true,
  },
  {
    name: "ollama",
    label: "Ollama (local)",
    model: "qwen2.5:7b-instruct",
    blurb: "Fully offline on your machine. No key.",
    keyHint: "",
    needsKey: false,
  },
  {
    name: "mock",
    label: "Mock",
    model: "mock",
    blurb: "No model at all. Try the app dry.",
    keyHint: "",
    needsKey: false,
  },
] as const;

const STEPS = ["Welcome", "Model", "Vault", "Ready"];

export function Onboarding() {
  const config = useStore((state) => state.config);
  const update = useStore((state) => state.update);
  const notify = useStore((state) => state.notify);
  const setBackend = useStore((state) => state.setBackend);
  const refresh = useStore((state) => state.refresh);

  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const [provider, setProvider] = useState(config?.provider ?? "aikey");
  const [model, setModel] = useState(config?.model ?? "deepseek-v4.1-flash:free");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verify, setVerify] = useState<{ ok: boolean; detail: string } | null>(null);
  const [vault, setVault] = useState(config?.vault ?? "");
  const [source, setSource] = useState(config?.source ?? "");
  const [finishing, setFinishing] = useState(false);

  const providerInfo = PROVIDERS.find((item) => item.name === provider) ?? PROVIDERS[0];

  const next = () => {
    setDirection(1);
    setStep((value) => Math.min(STEPS.length - 1, value + 1));
  };
  const back = () => {
    setDirection(-1);
    setStep((value) => Math.max(0, value - 1));
  };

  const chooseProvider = (name: string) => {
    const info = PROVIDERS.find((item) => item.name === name) ?? PROVIDERS[0];
    setProvider(name);
    setModel(info.model);
    setVerify(null);
  };

  const testKey = async () => {
    setVerifying(true);
    setVerify(null);
    try {
      const result = await bridge.verifyApiKey(provider, apiKey);
      setVerify(result);
    } catch (error) {
      setVerify({ ok: false, detail: error instanceof Error ? error.message : String(error) });
    } finally {
      setVerifying(false);
    }
  };

  const pickVault = async () => {
    const picked = await bridge.pickFolder("Choose where notes are written");
    if (picked) setVault(picked);
  };
  const pickSource = async () => {
    const picked = await bridge.pickFolder("Choose the folder with your videos and slides");
    if (picked) setSource(picked);
  };

  const finish = async () => {
    setFinishing(true);
    try {
      if (providerInfo.needsKey && apiKey.trim()) await bridge.saveApiKey(provider, apiKey.trim());
      await update({
        onboarded: true,
        vault: vault.trim(),
        source: source.trim(),
        provider,
        model,
        lastOpened: Date.now(),
      });
      const backend = await bridge.restartBackend();
      setBackend(backend);
      let status = backend;
      for (let i = 0; i < 30 && !status.ready; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        status = await bridge.backendStatus();
        setBackend(status);
      }
      celebrate("onboard");
      if (status.ready) {
        await refresh();
        notify("You're set", "Your cockpit is live. Enjoy the quiet hum.", "success");
      } else {
        notify("Vault saved", "The local engine didn't answer yet. You can retry from Settings.", "error");
      }
    } catch (error) {
      notify("Setup hit a snag", error instanceof Error ? error.message : String(error), "error");
    } finally {
      setFinishing(false);
    }
  };

  const canNext =
    step === 0 ||
    (step === 1 && (!providerInfo.needsKey || apiKey.trim().length > 0)) ||
    (step === 2 && vault.trim().length > 0);

  return (
    <div className="grain relative flex h-screen overflow-hidden bg-bg">
      <div className="pointer-events-none absolute -left-40 top-1/4 h-[420px] w-[420px] rounded-full bg-accent/20 blur-[120px]" />
      <div className="pointer-events-none absolute -right-32 bottom-0 h-[380px] w-[380px] rounded-full bg-iris/20 blur-[120px]" />

      <div className="relative z-10 hidden w-[46%] flex-col justify-between p-12 lg:flex">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-accent to-iris text-base font-bold text-white shadow-glow">
            S
          </div>
          <span className="font-display text-xl">Shellslatee</span>
        </div>

        <div className="max-w-md">
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-4 inline-flex items-center gap-2 rounded-full border border-accent/25 bg-accent/10 px-3 py-1 text-xs font-medium text-accent"
          >
            <Sparkles className="h-3.5 w-3.5" /> Local-first · your own key · no account
          </motion.p>
          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06 }}
            className="font-display text-[44px] leading-[1.06] tracking-tight"
          >
            Turn lectures into <span className="gradient-text">memory</span>.
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 }}
            className="mt-5 text-[15px] leading-relaxed text-muted"
          >
            Notes, transcripts, cards, quizzes and a concept graph — generated from your
            videos, slides and PDFs. Everything stays on your disk. You choose the model.
          </motion.p>

          <div className="mt-9 grid grid-cols-2 gap-3">
            {[
              { icon: Wand2, title: "Notes that remember", body: "Timestamped, structured, searchable." },
              { icon: ShieldCheck, title: "Private by default", body: "Vault on disk, key in your control." },
              { icon: Sparkles, title: "Recall, not rereading", body: "FSRS cards + explain-back coach." },
              { icon: Scissors, title: "Slides & PDFs too", body: "No microphone required." },
            ].map((feature, index) => (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.18 + index * 0.06 }}
                className="rounded-xl2 border bg-surface/60 p-3.5 backdrop-blur"
              >
                <feature.icon className="mb-2 h-4 w-4 text-accent" />
                <p className="text-[13px] font-medium leading-tight">{feature.title}</p>
                <p className="mt-1 text-[11px] leading-snug text-muted">{feature.body}</p>
              </motion.div>
            ))}
          </div>
        </div>

        <p className="text-[11px] text-muted">
          BYO key. Never uploaded anywhere except the provider you pick.
        </p>
      </div>

      <div className="relative z-10 flex flex-1 items-center justify-center p-5">
        <div className="w-full max-w-[520px] rounded-xl3 border bg-surface/85 p-7 shadow-lift backdrop-blur-xl">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-2">
              {STEPS.map((label, index) => (
                <div key={label} className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setDirection(index > step ? 1 : -1);
                      setStep(index);
                    }}
                    className={cn(
                      "grid h-6 w-6 place-items-center rounded-full border text-[10px] font-semibold transition",
                      index < step && "border-accent/40 bg-accent/15 text-accent",
                      index === step && "border-accent bg-accent text-white",
                      index > step && "border-line text-muted",
                    )}
                  >
                    {index < step ? <Check className="h-3 w-3" /> : index + 1}
                  </button>
                  {index < STEPS.length - 1 ? (
                    <div className={cn("h-px w-6", index < step ? "bg-accent/40" : "bg-line")} />
                  ) : null}
                </div>
              ))}
            </div>
            <span className="text-[11px] text-muted">{STEPS[step]}</span>
          </div>

          <div className="relative min-h-[330px] overflow-hidden">
            <AnimatePresence mode="wait" custom={direction} initial={false}>
              <motion.div
                key={step}
                custom={direction}
                variants={slideStep}
                initial="initial"
                animate="enter"
                exit="exit"
                className="space-y-5"
              >
                {step === 0 ? (
                  <>
                    <div>
                      <h2 className="font-display text-2xl">Hey — glad you're here.</h2>
                      <p className="mt-2 text-sm leading-relaxed text-muted">
                        Two minutes and you'll have a study cockpit that turns a folder of
                        lectures into notes you can actually revise from.
                      </p>
                    </div>
                    <div className="space-y-2.5 rounded-xl2 border bg-bg/50 p-4">
                      {[
                        "Point it at a course folder — videos, audio, PDFs, slide decks.",
                        "It transcribes locally (whisper.cpp) and writes structured notes.",
                        "Cards, quizzes and a graph are built from those notes.",
                        "You bring the API key. Nothing leaves your machine except prompts.",
                      ].map((line) => (
                        <p key={line} className="flex items-start gap-2 text-[13px] text-ink/85">
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                          {line}
                        </p>
                      ))}
                    </div>
                  </>
                ) : null}

                {step === 1 ? (
                  <>
                    <div>
                      <h2 className="font-display text-2xl">Pick your brain</h2>
                      <p className="mt-1.5 text-sm text-muted">
                        Use your own key. This app never proxies it and never bills you.
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      {PROVIDERS.map((item) => (
                        <button
                          key={item.name}
                          onClick={() => chooseProvider(item.name)}
                          className={cn(
                            "rounded-xl border p-3 text-left transition",
                            provider === item.name
                              ? "border-accent/60 bg-accent/10 shadow-glow"
                              : "hover:border-accent/30",
                          )}
                        >
                          <p className="text-[13px] font-semibold">{item.label}</p>
                          <p className="mt-0.5 text-[11px] leading-snug text-muted">{item.blurb}</p>
                        </button>
                      ))}
                    </div>

                    <div className="space-y-2">
                      <label className="label flex items-center gap-1.5">
                        <KeyRound className="h-3 w-3" /> API key
                      </label>
                      <div className="relative">
                        <Input
                          type={showKey ? "text" : "password"}
                          value={apiKey}
                          onChange={(event) => {
                            setApiKey(event.target.value);
                            setVerify(null);
                          }}
                          placeholder={providerInfo.needsKey ? `Paste your ${providerInfo.label} key` : "Not needed for this provider"}
                          disabled={!providerInfo.needsKey}
                          className="pr-10 font-mono text-xs"
                          autoComplete="off"
                          spellCheck={false}
                        />
                        <button
                          onClick={() => setShowKey((value) => !value)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted hover:text-ink"
                          type="button"
                        >
                          {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-[11px] text-muted">
                          {providerInfo.needsKey
                            ? `Get one at ${providerInfo.keyHint}. Stored locally.`
                            : "Runs against your local Ollama daemon."}
                        </p>
                        {providerInfo.needsKey ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={testKey}
                            disabled={!apiKey.trim()}
                            loading={verifying}
                          >
                            Test key
                          </Button>
                        ) : null}
                      </div>
                      <AnimatePresence>
                        {verify ? (
                          <motion.p
                            initial={{ opacity: 0, y: -4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0 }}
                            className={cn(
                              "flex items-start gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px]",
                              verify.ok ? "border-good/30 bg-good/10 text-good" : "border-bad/30 bg-bad/10 text-bad",
                            )}
                          >
                            {verify.ok ? <CheckCircle2 className="mt-0.5 h-3 w-3" /> : <XCircle className="mt-0.5 h-3 w-3" />}
                            {verify.detail}
                          </motion.p>
                        ) : null}
                      </AnimatePresence>
                    </div>

                    <div>
                      <label className="label">Model</label>
                      <Input value={model} onChange={(event) => setModel(event.target.value)} className="font-mono text-xs" />
                      <p className="mt-1 text-[11px] text-muted">
                        Defaults to {providerInfo.model}. Free models cost $0; paid ones bill the provider directly.
                      </p>
                    </div>
                  </>
                ) : null}

                {step === 2 ? (
                  <>
                    <div>
                      <h2 className="font-display text-2xl">Where do notes live?</h2>
                      <p className="mt-1.5 text-sm text-muted">
                        A folder on your disk. Plain Markdown, no lock-in, readable in any editor.
                      </p>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="label">Notes vault (output)</label>
                        <div className="flex gap-2">
                          <Input value={vault} onChange={(event) => setVault(event.target.value)} placeholder="C:\\Users\\you\\Shellslatee\\notes" className="font-mono text-xs" />
                          <Button variant="outline" size="sm" onClick={pickVault} icon={<FolderOpen className="h-3.5 w-3.5" />}>
                            Browse
                          </Button>
                        </div>
                        <button
                          type="button"
                          onClick={async () => {
                            const suggestion = await bridge.defaultVault();
                            if (suggestion) setVault(suggestion);
                          }}
                          className="mt-1.5 text-[11px] text-accent underline-offset-2 hover:underline"
                        >
                          Use the default location (Documents / Shellslatee Vault)
                        </button>
                      </div>
                      <div>
                        <label className="label">Course sources (optional)</label>
                        <div className="flex gap-2">
                          <Input value={source} onChange={(event) => setSource(event.target.value)} placeholder="Folder of videos / PDFs / slides" className="font-mono text-xs" />
                          <Button variant="outline" size="sm" onClick={pickSource} icon={<FolderOpen className="h-3.5 w-3.5" />}>
                            Browse
                          </Button>
                        </div>
                        <p className="mt-1 text-[11px] text-muted">
                          You can add or change this later. Videos never leave your machine.
                        </p>
                      </div>
                    </div>
                    <div className="rounded-xl2 border border-good/25 bg-good/5 p-3.5">
                      <p className="flex items-center gap-2 text-[12px] font-medium text-good">
                        <ShieldCheck className="h-4 w-4" /> Privacy, plainly
                      </p>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted">
                        Transcription runs locally. Only the text prompt goes to the model you
                        chose. No account, no telemetry, no syncing.
                      </p>
                    </div>
                  </>
                ) : null}

                {step === 3 ? (
                  <>
                    <div className="text-center">
                      <motion.div
                        initial={{ scale: 0.7, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ type: "spring", stiffness: 260, damping: 18 }}
                        className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-accent to-iris text-white shadow-glow"
                      >
                        <Sparkles className="h-7 w-7" />
                      </motion.div>
                      <h2 className="font-display text-2xl">Your cockpit is ready</h2>
                      <p className="mx-auto mt-2 max-w-sm text-sm text-muted">
                        We'll start the local engine and check the vault. If anything is off,
                        Settings will tell you exactly what.
                      </p>
                    </div>
                    <div className="space-y-2 rounded-xl2 border bg-bg/50 p-4 text-[12px]">
                      <Row label="Provider" value={`${providerInfo.label} · ${model}`} />
                      <Row label="Vault" value={vault || "not set"} mono />
                      <Row label="Sources" value={source || "none yet"} mono />
                      <Row label="Key" value={providerInfo.needsKey ? (apiKey.trim() ? "saved locally" : "not provided") : "not needed"} />
                    </div>
                    {finishing ? (
                      <p className="flex items-center justify-center gap-2 py-2 text-xs text-muted">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Starting the engine…
                      </p>
                    ) : null}
                  </>
                ) : null}
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="mt-6 flex items-center justify-between">
            <Button variant="ghost" onClick={back} disabled={step === 0} icon={<ArrowLeft className="h-4 w-4" />}>
              Back
            </Button>
            {step < STEPS.length - 1 ? (
              <Button onClick={next} disabled={!canNext} icon={<ArrowRight className="h-4 w-4" />}>
                Continue
              </Button>
            ) : (
              <Button onClick={finish} loading={finishing} disabled={!vault.trim()}>
                Enter Shellslatee
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted">{label}</span>
      <span className={cn("max-w-[65%] truncate text-right", mono && "font-mono text-[11px]")}>{value}</span>
    </div>
  );
}
