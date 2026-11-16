import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { pageVariants } from "@/lib/motion";
import { useStore } from "@/lib/store";
import { CaptureModal } from "./CaptureModal";
import { IngestModal } from "./IngestModal";
import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const setPalette = useStore((state) => state.setPalette);
  const ingestOpen = useStore((state) => state.ingestOpen);
  const setIngest = useStore((state) => state.setIngest);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (!typing && event.key === "/") {
        event.preventDefault();
        setPalette(true);
      }
      if (!typing && event.key.toLowerCase() === "n" && !mod) {
        event.preventDefault();
        setCaptureOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPalette]);

  useEffect(() => {
    let chord = false;
    let timer = 0;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      const key = event.key.toLowerCase();
      if (key === "g") {
        chord = true;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => (chord = false), 900);
        return;
      }
      if (!chord) return;
      chord = false;
      const routes: Record<string, string> = {
        h: "/",
        l: "/library",
        s: "/study",
        a: "/ask",
        g: "/graph",
        t: "/settings",
      };
      if (routes[key]) {
        event.preventDefault();
        navigate(routes[key]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
    };
  }, [navigate]);

  return (
    <div className="grain flex h-screen overflow-hidden bg-bg">
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      <AnimatePresence>
        {mobileOpen ? (
          <motion.div
            className="fixed inset-0 z-50 lg:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
            <motion.div
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: "spring", stiffness: 320, damping: 32 }}
              className="relative h-full w-[260px] bg-surface shadow-lift"
            >
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setMobileOpen(true)} onCapture={() => setCaptureOpen(true)} />
        <main className="relative min-h-0 flex-1 overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              variants={pageVariants}
              initial="initial"
              animate="enter"
              exit="exit"
              className="mx-auto w-full max-w-[1180px] px-5 py-6 md:px-8 md:py-8"
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <CommandPalette onCapture={() => setCaptureOpen(true)} />
      <CaptureModal open={captureOpen} onClose={() => setCaptureOpen(false)} />
      <IngestModal open={ingestOpen} onClose={() => setIngest(false)} />
    </div>
  );
}
