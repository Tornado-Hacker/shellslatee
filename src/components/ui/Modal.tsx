import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { scaleIn } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const widths = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl" };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[80] grid place-items-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            variants={scaleIn}
            initial="initial"
            animate="enter"
            exit="exit"
            className={cn("relative w-full overflow-hidden rounded-xl3 border bg-surface shadow-lift", widths[size])}
          >
            <div className="flex items-start justify-between gap-4 border-b px-6 py-4">
              <div>
                <h3 className="text-base font-semibold">{title}</h3>
                {description ? <p className="mt-0.5 text-sm text-muted">{description}</p> : null}
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-muted transition hover:bg-ink/5 hover:text-ink"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {children ? <div className="max-h-[65vh] overflow-y-auto px-6 py-5">{children}</div> : null}
            {footer ? <div className="flex justify-end gap-2 border-t px-6 py-4">{footer}</div> : null}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
