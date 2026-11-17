import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConnectionScreen } from "./components/ConnectionScreen";
import { Onboarding } from "./components/Onboarding";
import { Shell } from "./components/Shell";
import { Toasts } from "./components/ui/Toasts";
import { isTauri } from "./lib/bridge";
import { useStore } from "./lib/store";
import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { HomePage } from "./pages/HomePage";
import { LibraryPage } from "./pages/LibraryPage";
import { NotePage } from "./pages/NotePage";
import { SettingsPage } from "./pages/SettingsPage";
import { StudyPage } from "./pages/StudyPage";

function Splash() {
  return (
    <div className="grain grid h-screen place-items-center bg-bg">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        className="flex flex-col items-center gap-5"
      >
        <div className="relative">
          <div className="absolute inset-0 animate-pulseRing rounded-2xl bg-accent/30" />
          <div className="relative grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-accent to-iris text-xl font-bold text-white shadow-glow">
            S
          </div>
        </div>
        <div className="text-center">
          <p className="font-display text-lg">Warming the desk…</p>
          <p className="mt-1 text-xs text-muted">Checking the vault and the local engine</p>
        </div>
        <div className="flex gap-1.5">
          {[0, 1, 2].map((index) => (
            <motion.span
              key={index}
              className="h-1.5 w-1.5 rounded-full bg-accent"
              animate={{ opacity: [0.25, 1, 0.25] }}
              transition={{ duration: 1.1, repeat: Infinity, delay: index * 0.16 }}
            />
          ))}
        </div>
      </motion.div>
    </div>
  );
}

export default function App() {
  const initialized = useStore((state) => state.initialized);
  const config = useStore((state) => state.config);
  const backend = useStore((state) => state.backend);
  const init = useStore((state) => state.init);

  useEffect(() => {
    void init();
  }, [init]);

  if (!initialized || !config) {
    return (
      <>
        <Splash />
        <Toasts />
      </>
    );
  }

  return (
    <>
      <AnimatePresence mode="wait">
        {isTauri && !backend.ready ? (
          <motion.div key="connection" className="h-screen" exit={{ opacity: 0 }}>
            <ConnectionScreen />
          </motion.div>
        ) : !config.onboarded ? (
          <motion.div key="onboarding" className="h-screen" exit={{ opacity: 0 }}>
            <Onboarding />
          </motion.div>
        ) : (
          <HashRouter key="app">
            <Routes>
              <Route element={<Shell />}>
                <Route index element={<HomePage />} />
                <Route path="library" element={<LibraryPage />} />
                <Route path="note/*" element={<NotePage />} />
                <Route path="study" element={<StudyPage />} />
                <Route path="ask" element={<AskPage />} />
                <Route path="graph" element={<GraphPage />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </HashRouter>
        )}
      </AnimatePresence>
      <Toasts />
    </>
  );
}
