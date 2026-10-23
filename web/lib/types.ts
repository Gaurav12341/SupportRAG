export type Role = "public" | "member" | "admin";
export const PRODUCTS = ["kubernetes", "postgres", "kafka", "github"] as const;
export type Product = (typeof PRODUCTS)[number];
export const PRODUCT_NAME: Record<Product, string> = { kubernetes: "Kubernetes", postgres: "PostgreSQL", kafka: "Kafka", github: "GitHub Actions" };
export type Level = "public" | "internal" | "restricted";

export type Session = { user: string | null; role: Role; licenses: Product[] };

export type Source = { chunk_id: string; title: string; url: string; product: Product };
export type Passage = { label: string; chunk_id: string; title: string; url: string; product: Product; access_level: Level; text: string };
export type Point = { text: string; cited: string[]; warnings: string[] };
export type AskResult = {
  status: "answered" | "refused" | "blocked";
  message: string;
  question_used: string;
  rewritten: boolean;
  products: string[];
  product_filter: string;
  dropped_chunks: [string, string][];
  block_rule: string;
  kind?: string;
  coverage?: string;
  provider?: string;
  verified_by?: string;
  summary?: string;
  partial_note?: string;
  summary_warnings?: string[];
  points?: Point[];
  sources?: Source[];
  passages?: Passage[];
};

export type Doc = {
  id: string;
  title: string;
  product: Product;
  source: "kubernetes" | "postgres" | "kafka" | "github" | "stackoverflow";
  doc_type: string;
  access_level: Level;
  url: string;
  license: string;
  version: string;
  chunks: number;
};
export type Library = { documents: Doc[]; locked: Partial<Record<Product, number>>; totals: Record<Product, number>; chunks: number };

export type AdminUser = { user: string; role: "member" | "admin"; licenses: Product[]; created_at: number | null; created_by: string | null };
export type AuditEntry = { at: number; actor: string; action: string; user_id: string; product: Product | null };

export type Interval = [number, number];
export type SafetyRun = {
  attacks: number;
  attacks_blocked: number;
  normal: number;
  normal_blocked: number;
  poisoned: number;
  poisoned_caught: number;
  real_chunks: number;
  real_chunks_flagged: number;
};
export type Metrics = {
  holdout: null | {
    n: number;
    answerable: number;
    unanswerable: number;
    accuracy: number;
    ci95: Interval;
    correct: number;
    outcomes: { correct: number; partial: number; incorrect: number; false_refusal: number; correctly_refused: number };
    by_type: { type: string; n: number; correct: number; correct_verifier_off: number }[];
    failures: Record<string, number>;
    evidence_in_context: number;
    wrong_claim_shown: number;
    setup: { split: string; writer: string; judge: string; verifier: string; k_context: number; embedding: string; collection: string; retry: boolean };
    tokens: Record<string, { calls: number; total: number }>;
  };
  progress: { file: string; current: boolean; label: string; split: string; n: number; accuracy: number; ci95: Interval; draft_accuracy: number }[];
  retrieval: { file: string; label: string; n: number; recall5: number; recall10: number; mrr: number; median_ms: number | null }[];
  safety: null | SafetyRun;
  safety_first_run: null | SafetyRun;
};
