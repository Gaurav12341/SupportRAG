"use client";
import { ArrowUp, CircleAlert, Lock, RefreshCw, ShieldAlert, SquarePen } from "lucide-react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, ApiError } from "@/lib/client";
import { clean } from "@/lib/richtext";
import { PRODUCT_NAME, PRODUCTS, type AskResult, type Product, type Session } from "@/lib/types";
import { EvidencePanel, SearchingStrip, type Scope } from "./EvidencePanel";
import { Rich } from "./Rich";

const MAX_CHARS = 1000; // the guard's limit (config.yaml input.max_chars); the server is the authority and explains itself if it differs
const HISTORY_TURNS = 3;
const STARTERS = [
  "psql says: FATAL: password authentication failed for user",
  "A pod is stuck in CrashLoopBackOff. Where do I start?",
  "A Kafka consumer group keeps rebalancing",
  "A GitHub Actions workflow does not run on push",
];
const EASE_OUT = [0.23, 1, 0.32, 1] as const;

type Turn = { id: number; question: string; product: Product | ""; state: "pending" | "done" | "error"; result?: AskResult; error?: string };

export function Chat({ session, scope }: { session: Session; scope: Scope }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [product, setProduct] = useState<Product | "">("");
  const [selected, setSelected] = useState<number | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const nextId = useRef(1);
  const box = useRef<HTMLTextAreaElement>(null);
  const last = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();

  const busy = turns.some((t) => t.state === "pending");
  const shown = turns.find((t) => t.id === selected) ?? [...turns].reverse().find((t) => t.state === "done") ?? null;

  useEffect(() => {
    last.current?.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }, [turns.length, reduce]);

  const resize = useCallback(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);
  useEffect(resize, [draft, resize]);

  async function send(question: string, chosen: Product | "" = product, retryOf?: number) {
    const text = question.trim();
    if (!text || busy) return;
    const id = retryOf ?? nextId.current++;
    const history = turns
      .filter((t) => t.state === "done" && t.result?.status === "answered" && t.id !== id)
      .slice(-HISTORY_TURNS)
      .map((t) => ({ q: t.question, a: (t.result!.summary || t.result!.points?.[0]?.text || "").slice(0, 4000) }));
    setTurns((all) => (retryOf ? all.map((t) => (t.id === id ? { ...t, state: "pending", error: undefined } : t)) : [...all, { id, question: text, product: chosen, state: "pending" }]));
    setSelected(null);
    setOpenId(null);
    if (!retryOf) setDraft("");
    try {
      const result = await api<AskResult>("ask", "POST", { question: text, history, product: chosen || null });
      setTurns((all) => all.map((t) => (t.id === id ? { ...t, state: "done", result } : t)));
    } catch (e) {
      setTurns((all) => all.map((t) => (t.id === id ? { ...t, state: "error", error: e instanceof ApiError ? e.message : "Something went wrong." } : t)));
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(draft);
    }
  }

  function openPassage(id: string | null) {
    setOpenId(id);
    if (id) requestAnimationFrame(() => document.getElementById(`passage-${shown?.result?.passages?.find((p) => p.chunk_id === id)?.label}`)?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" }));
  }

  const over = draft.length > MAX_CHARS;

  return (
    <div className="ask">
      <section className="thread-col" aria-label="Conversation" data-active={turns.length > 0}>
        <div className="title-row">
          <div>
            <h1>Ask</h1>
            <p className="subline">Answers cite the documentation. If it has no fix, you are told so instead of getting a guess.</p>
          </div>
          {turns.length > 0 && (
            <button className="btn btn-secondary btn-sm" onClick={() => { setTurns([]); setSelected(null); setOpenId(null); box.current?.focus(); }} disabled={busy}>
              <SquarePen size={14} strokeWidth={1.5} aria-hidden="true" /> New conversation
            </button>
          )}
        </div>

        <div className="thread" aria-live="polite">
          {turns.length === 0 && (
            <div className="starters">
              <p className="muted">Paste an error message or describe the symptom. Try one of these:</p>
              <ul>
                {STARTERS.map((s) => (
                  <li key={s}><button onClick={() => void send(s)}>{s}</button></li>
                ))}
              </ul>
              {scope && (
                <p className="small muted">
                  <Lock size={12} strokeWidth={1.5} aria-hidden="true" />
                  <span>
                    You can read {scope.pages.toLocaleString("en-US")} pages.{" "}
                    {scope.locked > 0 ? <>{scope.locked.toLocaleString("en-US")} more are locked for this account. <Link href="/documents">See which</Link>.</> : "Nothing is locked for this account."}
                  </span>
                </p>
              )}
            </div>
          )}

          {turns.map((t, i) => (
            <motion.article
              key={t.id}
              ref={i === turns.length - 1 ? last : undefined}
              className="turn"
              data-selected={shown?.id === t.id}
              initial={{ opacity: 0, transform: "translateY(8px)" }}
              animate={{ opacity: 1, transform: "translateY(0px)" }}
              transition={{ duration: 0.22, ease: EASE_OUT }}
            >
              <p className="question">
                {t.question}
                {t.product && <span className="pill">{PRODUCT_NAME[t.product]}</span>}
              </p>
              {t.state === "pending" && (
                <div className="answer card waiting" role="status">
                  <SearchingStrip />
                  <p>Searching the documentation and writing an answer. This usually takes between 5 and 30 seconds.</p>
                </div>
              )}
              {t.state === "error" && (
                <div className="answer card problem" role="alert">
                  <CircleAlert size={16} strokeWidth={1.5} aria-hidden="true" />
                  <div>
                    <p>{t.error}</p>
                    <button className="btn btn-secondary btn-sm" onClick={() => void send(t.question, t.product, t.id)} disabled={busy}>
                      <RefreshCw size={14} strokeWidth={1.5} aria-hidden="true" /> Try again
                    </button>
                  </div>
                </div>
              )}
              {t.state === "done" && t.result && (
                <AnswerCard
                  result={t.result}
                  scope={scope}
                  activeId={shown?.id === t.id ? activeId : null}
                  onActive={setActiveId}
                  onOpen={(id) => { setSelected(t.id); openPassage(id); }}
                  onSelect={() => setSelected(t.id)}
                  isAdmin={session.role === "admin"}
                />
              )}
            </motion.article>
          ))}
        </div>

        <form className="composer card" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
          <label className="sr-only" htmlFor="q">Your question</label>
          <textarea
            id="q" ref={box} rows={2} value={draft} placeholder="Paste an error message or describe what is going wrong"
            onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} aria-describedby="q-hint"
          />
          <div className="composer-bar">
            <label className="select-inline">
              <span className="sr-only">Product</span>
              <select value={product} onChange={(e) => setProduct(e.target.value as Product | "")}>
                <option value="">All products</option>
                {PRODUCTS.map((p) => <option key={p} value={p}>{PRODUCT_NAME[p]}</option>)}
              </select>
            </label>
            <span id="q-hint" className="small muted hint">Enter to send, Shift+Enter for a new line</span>
            {draft.length > MAX_CHARS * 0.8 && <span className="small num" data-over={over}>{draft.length}/{MAX_CHARS}</span>}
            <button className="btn btn-primary btn-icon-label" disabled={busy || !draft.trim()}>
              Ask <ArrowUp size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </div>
        </form>
      </section>

      <EvidencePanel result={shown?.result ?? null} activeId={activeId} openId={openId} onActive={setActiveId} onOpen={openPassage} scope={scope} />
    </div>
  );
}

function AnswerCard({ result, scope, activeId, onActive, onOpen, onSelect, isAdmin }: {
  result: AskResult; scope: Scope; activeId: string | null; isAdmin: boolean;
  onActive: (id: string | null) => void; onOpen: (id: string) => void; onSelect: () => void;
}) {
  if (result.status === "blocked") {
    return (
      <div className="answer card problem" role="status">
        <ShieldAlert size={16} strokeWidth={1.5} aria-hidden="true" />
        <div>
          <h3>Question not run</h3>
          <p>{clean(result.message)}</p>
        </div>
      </div>
    );
  }
  if (result.status === "refused") {
    return (
      <div className="answer card refused" onClick={onSelect}>
        <h3>No documented fix found</h3>
        <p>
          The documentation this account can read does not answer that, and a guess would be worse than saying so. Reword it with the exact error text or
          setting name, pick the product, or read the closest passages in the evidence panel.
        </p>
        {scope && scope.locked > 0 && (
          <p className="small muted">
            <Lock size={12} strokeWidth={1.5} aria-hidden="true" />
            <span>
              {scope.locked.toLocaleString("en-US")} pages are locked for this account.{" "}
              {isAdmin ? "" : "If the fix could be in them, ask an admin for a license."}
            </span>
          </p>
        )}
      </div>
    );
  }
  const number = Object.fromEntries((result.sources ?? []).map((s, i) => [s.chunk_id, i + 1]));
  return (
    <div className="answer card" onClick={onSelect}>
      {result.summary && <Rich text={result.summary} className="summary" />}
      {(result.summary_warnings ?? []).map((w, i) => <Warning key={i} text={w} />)}
      {result.partial_note && <p className="muted partial">{clean(result.partial_note)}</p>}
      <ol className="steps">
        {(result.points ?? []).map((p, i) => (
          <motion.li
            key={i}
            initial={{ opacity: 0, transform: "translateY(6px)" }}
            animate={{ opacity: 1, transform: "translateY(0px)" }}
            transition={{ duration: 0.2, ease: EASE_OUT, delay: Math.min(i, 6) * 0.045 }}
          >
            <Rich text={p.text} />
            <span className="cites">
              {p.cited.filter((c) => number[c]).map((c) => (
                <button
                  key={c} className="cite" data-active={activeId === c}
                  aria-label={`Source ${number[c]}: ${clean(result.sources!.find((s) => s.chunk_id === c)!.title)}`}
                  onMouseEnter={() => onActive(c)} onMouseLeave={() => onActive(null)} onFocus={() => onActive(c)} onBlur={() => onActive(null)}
                  onClick={() => onOpen(c)}
                >
                  {number[c]}
                </button>
              ))}
            </span>
            {p.warnings.map((w, j) => <Warning key={j} text={w} />)}
          </motion.li>
        ))}
      </ol>
    </div>
  );
}

function Warning({ text }: { text: string }) {
  return (
    <p className="warning" role="note">
      <ShieldAlert size={14} strokeWidth={1.5} aria-hidden="true" /> {clean(text)}
    </p>
  );
}
