import { isTauri } from "./bridge";
import type {
  ActionName,
  ActionResult,
  AiTurn,
  AskResult,
  Card,
  CardsQueue,
  AsrApply,
  AsrStatus,
  CourseAnswer,
  DoctorReport,
  DrillQueue,
  GraphPayload,
  Job,
  Note,
  Providers,
  QuizCheck,
  QuizQueue,
  SaveResult,
  ScanResult,
  SearchRow,
  Settings,
  Vault,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let base = "";

export function setApiBase(url: string | null) {
  base = url ?? "";
}

export function apiBase(): string {
  return base;
}

export function mediaUrl(rel: string | null | undefined): string | null {
  if (!rel) return null;
  if (/^https?:/i.test(rel)) return rel;
  return `${base}${rel}`;
}

async function invokeProxy(method: string, path: string, body?: string): Promise<string> {
  const mod = await import("@tauri-apps/api/core");
  return mod.invoke<string>("api_request", { method, path, body: body ?? null });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  const body = init?.body ? String(init.body) : undefined;
  let text = "";
  let status = 200;

  if (isTauri) {
    try {
      text = await invokeProxy(method, path, body);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const match = /^(\d{3})\s*/.exec(message);
      throw new ApiError(match ? Number(match[1]) : 500, message.replace(/^\d{3}\s*/, ""));
    }
  } else {
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    text = await response.text();
    status = response.status;
    if (!response.ok) {
      let message = `request failed (${status})`;
      try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === "object" && "error" in parsed) message = String(parsed.error);
      } catch {
        /* plain text body */
      }
      throw new ApiError(status, message);
    }
  }

  try {
    return (text ? JSON.parse(text) : null) as T;
  } catch {
    return text as unknown as T;
  }
}

function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<{ ok: boolean; version: string; web_built: boolean }>("/api/health"),
  providers: () => request<Providers>("/api/providers"),
  settings: (out: string) => request<Settings>(`/api/settings${qs({ out })}`),
  scan: (source: string, durations = false) =>
    request<ScanResult>(`/api/scan${qs({ source, durations: durations ? 1 : undefined })}`),
  vault: (out: string, source?: string) => request<Vault>(`/api/vault${qs({ out, source })}`),
  note: (out: string, rel: string, source?: string) =>
    request<Note>(`/api/note${qs({ out, rel, source })}`),
  search: (out: string, q: string, mode: "fts" | "hybrid" | "semantic" = "fts") =>
    request<{ rows: SearchRow[]; mode: string }>(`/api/search${qs({ out, q, mode })}`),
  run: (payload: Record<string, unknown>) =>
    request<Job>("/api/run", { method: "POST", body: JSON.stringify(payload) }),
  ask: (payload: {
    out: string;
    rel: string;
    source?: string;
    question: string;
    mode?: "ask" | "edit";
    provider?: string;
    model?: string;
    history?: AiTurn[];
  }) => request<AskResult>("/api/ask", { method: "POST", body: JSON.stringify(payload) }),
  saveNote: (payload: { out: string; rel: string; markdown: string }) =>
    request<SaveResult>("/api/note/write", { method: "POST", body: JSON.stringify(payload) }),
  action: (payload: {
    out: string;
    rel: string;
    text: string;
    action: ActionName;
    concept?: string;
    provider?: string;
    model?: string;
  }) => request<ActionResult>("/api/action", { method: "POST", body: JSON.stringify(payload) }),
  doctor: () => request<DoctorReport>("/api/doctor"),
  asrStatus: () => request<AsrStatus>("/api/asr/status"),
  asrProvision: (model = "tiny.en", force = false) =>
    request<Job>("/api/asr/provision", {
      method: "POST",
      body: JSON.stringify({ model, force }),
    }),
  asrApply: () => request<AsrApply>("/api/asr/apply", { method: "POST" }),
  askCourse: (payload: { out: string; question: string; provider?: string; model?: string }) =>
    request<CourseAnswer>("/api/ask_course", { method: "POST", body: JSON.stringify(payload) }),
  cards: (out: string, limit = 20) => request<CardsQueue>(`/api/cards${qs({ out, limit })}`),
  drills: (out: string, limit = 20) => request<DrillQueue>(`/api/cards/drills${qs({ out, limit })}`),
  buildCards: (out: string) =>
    request<{ created: number; updated: number; total: number }>("/api/cards/build", {
      method: "POST",
      body: JSON.stringify({ out }),
    }),
  reviewCard: (out: string, id: string, grade: number) =>
    request<Card>("/api/cards/review", {
      method: "POST",
      body: JSON.stringify({ out, id, grade }),
    }),
  capture: (out: string, text: string, tag?: string) =>
    request<{ path: string; line: string }>("/api/capture", {
      method: "POST",
      body: JSON.stringify({ out, text, tag }),
    }),
  graph: (out: string, semantic = false) =>
    request<GraphPayload>(`/api/graph${qs({ out, semantic: semantic ? 1 : undefined })}`),
  quiz: (out: string, limit = 50, kind?: "mcq" | "short") =>
    request<QuizQueue>(`/api/quiz${qs({ out, limit, kind })}`),
  buildQuiz: (out: string, focus?: string[]) =>
    request<{ created: number; updated: number; total: number; pruned: number; stats: QuizQueue["stats"] }>(
      "/api/quiz/build",
      { method: "POST", body: JSON.stringify({ out, focus }) },
    ),
  checkQuiz: (out: string, id: string, response: string) =>
    request<QuizCheck>("/api/quiz/check", {
      method: "POST",
      body: JSON.stringify({ out, id, response }),
    }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  jobs: () => request<{ jobs: Job[] }>("/api/jobs"),
  stop: (id: string) => request<Job>(`/api/jobs/${id}/stop`, { method: "POST" }),
  pause: (id: string) => request<Job>(`/api/jobs/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request<Job>(`/api/jobs/${id}/resume`, { method: "POST" }),
};
