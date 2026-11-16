import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useStore } from "@/lib/store";

export function Toasts() {
  const toasts = useStore((state) => state.toasts);
  const dismiss = useStore((state) => state.dismiss);

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[95] flex w-80 flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((toast) => {
          const Icon = toast.tone === "success" ? CheckCircle2 : toast.tone === "error" ? AlertTriangle : Info;
          const tone =
            toast.tone === "success" ? "text-good" : toast.tone === "error" ? "text-bad" : "text-iris";
          return (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 30, scale: 0.97 }}
              transition={{ type: "spring", stiffness: 380, damping: 32 }}
              className="pointer-events-auto flex items-start gap-3 rounded-xl border bg-elevated/95 p-3.5 shadow-lift backdrop-blur"
            >
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium leading-tight">{toast.title}</p>
                {toast.message ? <p className="mt-0.5 break-words text-xs text-muted">{toast.message}</p> : null}
              </div>
              <button onClick={() => dismiss(toast.id)} className="rounded p-1 text-muted hover:text-ink">
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
