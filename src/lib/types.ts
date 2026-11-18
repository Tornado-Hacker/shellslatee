export type Lesson = {
  rel: string;
  title: string;
  module: string;
  summary: string;
  duration: number;
  tags: string[];
  concepts: string[];
  video: string | null;
  video_rel: string | null;
};

export type DoctorCheck = {
  name: string;
  ok: boolean;
  detail: string;
};

export type DoctorReport = {
  checks: DoctorCheck[];
  ready: boolean;
};

export type AsrStatus = {
  target: string;
  bin: string;
  present: { ffmpeg: boolean; ffprobe: boolean; whisper: boolean; models: string[] };
  missing: string[];
  has_env: boolean;
  checks: DoctorCheck[];
  ready: boolean;
  models_available: string[];
};

export type AsrApply = {
  env: Record<string, string>;
  checks: DoctorCheck[];
  ready: boolean;
};

export type Concept = {
  slug: string;
  name: string;
  definition: string;
  definitions: number;
  lessons: string[];
};

export type Vault = {
  out: string;
  source: string | null;
  title: string;
  lessons: Lesson[];
  concepts: Concept[];
  total_duration: number;
  has_index: boolean;
};

export type Segment = { start: number; heading: string; text: string };

export type Note = {
  rel: string;
  title: string;
  frontmatter: Record<string, string>;
  markdown: string;
  segments: Segment[];
  video: string | null;
  video_rel: string | null;
};

export type ScanItem = {
  rel: string;
  kind: string;
  bytes: number;
  subtitle: string | null;
  duration: number | null;
  video: string | null;
};

export type ScanResult = { source: string; count: number; items: ScanItem[] };

export type Provider = {
  name: string;
  base_url: string;
  default_model: string;
  ready: boolean;
  detail: string;
};

export type Providers = { default: string; default_ready: boolean; presets: Provider[] };

export type SearchRow = { path: string; title: string; snippet: string; section: string };

export type JobItem = { rel: string; status: string; detail: string };

export type Job = {
  id: string;
  status: string;
  paused: boolean;
  created: number;
  returncode: number | null;
  total: number;
  index: number;
  written: number;
  skipped: number;
  failed: number;
  usd: number;
  projection_usd: number | null;
  target: string;
  source: string;
  out: string;
  items: JobItem[];
  log: string[];
};

export type Settings = Providers & { stored: Record<string, unknown> };

export type AiTurn = { role: "user" | "assistant"; content: string };

export type AskResult = {
  mode: "ask" | "edit";
  answer: string;
  tokens: { in: number; out: number };
  provider: string;
  model: string;
};

export type SaveResult = { ok: boolean; rel: string; bytes: number; warnings: string[] };

export type Card = {
  id: string;
  lesson: string;
  kind: string;
  front: string;
  back: string;
  reps: number;
  lapses: number;
  due_ts: number;
  last_review: number;
  stability: number;
  difficulty: number;
  interval_s?: number;
  concept?: string | null;
  weakness?: number;
};

export type CardStats = { total: number; new: number; due: number };
export type CardsQueue = { stats: CardStats; cards: Card[] };

export type DrillGroup = { concept: string | null; lesson: string; weakness: number; cards: Card[] };
export type DrillQueue = { stats: CardStats; groups: DrillGroup[]; cards: Card[] };

export type Citation = {
  n: number;
  rel: string;
  title: string;
  section: string;
  start: number | null;
  snippet: string;
};

export type CourseAnswer = {
  answer: string;
  citations: Citation[];
  tokens: { in: number; out: number };
  provider: string;
  model: string;
};

export type ActionName = "explain" | "simplify" | "quiz" | "cards" | "related" | "link";
export type ActionCard = { front: string; back: string };

export type ActionResult = {
  action: ActionName;
  text: string;
  cards?: ActionCard[];
  citations?: Citation[];
  concept?: string;
  slug?: string;
  rel?: string;
  added?: boolean;
  tokens?: { in: number; out: number };
  provider?: string;
  model?: string;
};

export type GraphNode = {
  id: string;
  kind: "lesson" | "concept";
  label: string;
  rel?: string;
  slug?: string;
  module?: string;
};

export type GraphEdge = {
  src: string;
  dst: string;
  rel: "covers" | "related";
  weight?: number;
};

export type GraphPayload = { nodes: GraphNode[]; edges: GraphEdge[]; counts: Record<string, number> };

export type QuizItem = {
  id: string;
  lesson: string;
  concept: string | null;
  kind: "mcq" | "short";
  question: string;
  options: string[];
  answer: string;
  answer_index: number;
  explanation: string;
};

export type QuizStats = { total: number; mcq: number; short: number; attempts: number; correct: number };
export type QuizQueue = { stats: QuizStats; items: QuizItem[] };

export type QuizCheck = {
  id: string;
  correct: boolean;
  kind: "mcq" | "short";
  answer: string;
  answer_index: number;
  explanation: string;
  lesson: string;
  concept: string | null;
};

/* ---------------- desktop app domain ---------------- */

export type Theme = "dark" | "light";
export type Accent = "ember" | "iris" | "jade" | "cobalt";

export type AppConfig = {
  onboarded: boolean;
  vault: string;
  source: string;
  provider: string;
  model: string;
  theme: Theme;
  accent: Accent;
  examTitle: string;
  examDate: string;
  dailyMinutes: number;
  lastNote: string;
  lastOpened: number;
  streakDays: string[];
};

export type BackendStatus = {
  ready: boolean;
  base: string | null;
  error: string | null;
  version: string | null;
};

export type VerifyResult = { ok: boolean; detail: string };

export type PrereqReport = {
  python: string | null;
  python_hint: string | null;
  engine: boolean;
  wheel: boolean;
  wheel_path: string | null;
  ready: boolean;
};
