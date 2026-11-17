import { create } from "zustand";
import { api, setApiBase } from "./api";
import { bridge, isTauri } from "./bridge";
import type { AppConfig, BackendStatus, Vault } from "./types";

export type Tone = "info" | "success" | "error";
export type Toast = { id: number; title: string; message?: string; tone: Tone };

type Store = {
  config: AppConfig | null;
  backend: BackendStatus;
  vault: Vault | null;
  loadingVault: boolean;
  vaultError: string | null;
  initialized: boolean;
  toasts: Toast[];
  paletteOpen: boolean;
  ingestOpen: boolean;
  init: () => Promise<void>;
  update: (patch: Partial<AppConfig>) => Promise<void>;
  setBackend: (backend: BackendStatus) => void;
  refresh: () => Promise<void>;
  notify: (title: string, message?: string, tone?: Tone) => void;
  dismiss: (id: number) => void;
  setPalette: (open: boolean) => void;
  setIngest: (open: boolean) => void;
  reset: () => Promise<void>;
};

let toastSeq = 1;
let backendSubscribed = false;

function applyAppearance(config: AppConfig) {
  const root = document.documentElement;
  root.classList.toggle("dark", config.theme === "dark");
  root.style.colorScheme = config.theme;
  root.dataset.accent = config.accent;
  try {
    localStorage.setItem("shellslatee.theme", config.theme);
  } catch {
    /* ignore */
  }
}

export const useStore = create<Store>((set, get) => ({
  config: null,
  backend: { ready: false, base: null, error: null, version: null },
  vault: null,
  loadingVault: false,
  vaultError: null,
  initialized: false,
  toasts: [],
  paletteOpen: false,
  ingestOpen: false,

  async init() {
    let config = await bridge.loadConfig();
    // The installer creates the notes folder and leaves its path behind. Pick it
    // up here so the vault is prefilled instead of blank on a fresh install.
    if (isTauri && !config.vault) {
      try {
        const suggested = await bridge.defaultVault();
        if (suggested) {
          config = { ...config, vault: suggested };
          await bridge.saveConfig(config);
        }
      } catch {
        /* onboarding still lets the user pick a folder */
      }
    }
    applyAppearance(config);
    set({ config });
    const backend = await bridge.backendStatus();
    setApiBase(backend.base);
    set({ backend, initialized: true });
    if (backend.ready && config.vault) await get().refresh();

    if (isTauri && !backendSubscribed) {
      backendSubscribed = true;
      void bridge.onBackendStatus((status) => {
        get().setBackend(status);
        if (status.ready && get().config?.vault) void get().refresh();
      });
    }
  },

  async update(patch) {
    const current = get().config;
    if (!current) return;
    const next = { ...current, ...patch };
    set({ config: next });
    applyAppearance(next);
    await bridge.saveConfig(next);
    if (patch.vault !== undefined || patch.source !== undefined) await get().refresh();
  },

  setBackend(backend) {
    setApiBase(backend.base);
    set({ backend });
  },

  async refresh() {
    const { backend, config } = get();
    if (!config?.vault) {
      set({ vault: null, vaultError: null });
      return;
    }
    if (!backend.ready) {
      set({ vault: null, vaultError: "The local engine is not running." });
      return;
    }
    set({ loadingVault: true, vaultError: null });
    try {
      const vault = await api.vault(config.vault, config.source || undefined);
      set({ vault, loadingVault: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set({ vault: null, loadingVault: false, vaultError: message });
    }
  },

  notify(title, message, tone = "info") {
    const id = toastSeq++;
    set((state) => ({ toasts: [...state.toasts.slice(-3), { id, title, message, tone }] }));
    window.setTimeout(() => get().dismiss(id), tone === "error" ? 7000 : 4200);
  },

  dismiss(id) {
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }));
  },

  setPalette(open) {
    set({ paletteOpen: open });
  },

  setIngest(open) {
    set({ ingestOpen: open });
  },

  async reset() {
    if (!get().config) return;
    const fresh: AppConfig = {
      ...get().config!,
      onboarded: false,
      vault: "",
      source: "",
      examDate: "",
      examTitle: "",
      lastNote: "",
    };
    set({ config: fresh, vault: null });
    await bridge.saveConfig(fresh);
  },
}));
