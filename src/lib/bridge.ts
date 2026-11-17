import type { AppConfig, BackendStatus, PrereqReport, Theme, VerifyResult } from "./types";

export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type InvokeFn = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

let invokeFn: InvokeFn | null = null;

async function loadInvoke(): Promise<InvokeFn | null> {
  if (!isTauri) return null;
  if (!invokeFn) {
    const mod = await import("@tauri-apps/api/core");
    invokeFn = mod.invoke as InvokeFn;
  }
  return invokeFn;
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const invoke = await loadInvoke();
  if (!invoke) throw new Error("desktop bridge unavailable");
  return invoke<T>(cmd, args);
}

const STORE_KEY = "shellslatee.config";

function defaultConfig(): AppConfig {
  const prefs = typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  return {
    onboarded: false,
    vault: "",
    source: "",
    provider: "aikey",
    model: "deepseek-v4.1-flash:free",
    theme: prefs as Theme,
    accent: "ember",
    examTitle: "",
    examDate: "",
    dailyMinutes: 25,
    lastNote: "",
    lastOpened: Date.now(),
    streakDays: [],
  };
}

export const bridge = {
  async loadConfig(): Promise<AppConfig> {
    if (isTauri) {
      try {
        const stored = await call<Partial<AppConfig>>("load_config");
        return { ...defaultConfig(), ...stored };
      } catch {
        /* fall through to localStorage */
      }
    }
    try {
      const raw = localStorage.getItem(STORE_KEY);
      return raw ? { ...defaultConfig(), ...JSON.parse(raw) } : defaultConfig();
    } catch {
      return defaultConfig();
    }
  },

  async saveConfig(config: AppConfig): Promise<void> {
    if (isTauri) {
      try {
        await call("save_config", { config });
      } catch {
        /* ignore, mirror below */
      }
    }
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(config));
    } catch {
      /* storage full or private mode */
    }
  },

  async backendStatus(): Promise<BackendStatus> {
    if (isTauri) return call<BackendStatus>("backend_status");
    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error();
      const body = (await response.json()) as { version: string };
      return { ready: true, base: "", error: null, version: body.version };
    } catch {
      return { ready: false, base: null, error: "backend not reachable", version: null };
    }
  },

  async checkPrereqs(): Promise<PrereqReport> {
    if (!isTauri) {
      return { python: null, python_hint: null, engine: false, wheel: false, wheel_path: null, ready: false };
    }
    return call<PrereqReport>("check_prereqs");
  },

  async installPrereqs(): Promise<{ ok: boolean; python?: string; steps?: string[] }> {
    return call<{ ok: boolean; python?: string; steps?: string[] }>("install_prereqs");
  },

  async restartBackend(): Promise<BackendStatus> {
    if (!isTauri) return this.backendStatus();
    return call<BackendStatus>("restart_backend");
  },

  async saveApiKey(provider: string, key: string): Promise<void> {
    if (isTauri) return call<void>("save_api_key", { provider, key });
    localStorage.setItem(`shellslatee.key.${provider}`, key);
  },

  async clearApiKey(provider: string): Promise<void> {
    if (isTauri) return call<void>("clear_api_key", { provider });
    localStorage.removeItem(`shellslatee.key.${provider}`);
  },

  async verifyApiKey(provider: string, key: string): Promise<VerifyResult> {
    if (isTauri) return call<VerifyResult>("verify_api_key", { provider, key });
    return { ok: key.trim().length > 8, detail: "Looks plausible (browser preview can't call the provider)." };
  },

  async pickFolder(title: string): Promise<string | null> {
    if (!isTauri) return null;
    const { open } = await import("@tauri-apps/plugin-dialog");
    const picked = await open({ directory: true, multiple: false, title });
    return typeof picked === "string" ? picked : null;
  },

  async openPath(path: string): Promise<void> {
    if (isTauri) await call<void>("open_path", { path });
  },

  async defaultVault(): Promise<string> {
    if (!isTauri) return "";
    try {
      return await call<string>("default_vault");
    } catch {
      return "";
    }
  },

  platform(): string {
    if (!isTauri) return "browser";
    const nav = navigator.userAgent;
    if (nav.includes("Win")) return "windows";
    if (nav.includes("Mac")) return "macos";
    return "linux";
  },
};
