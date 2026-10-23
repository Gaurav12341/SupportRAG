"use client";
import { ChevronDown, ExternalLink, Lock } from "lucide-react";
import Link from "next/link";
import { safeUrl } from "@/lib/richtext";
import { PRODUCT_NAME, type AskResult, type Passage } from "@/lib/types";
import { clean } from "@/lib/richtext";
import { Rich } from "./Rich";

export type Scope = { pages: number; chunks: number; locked: number } | null;

/** The signature element: every passage the writer was given, in rank order. Cited ones are tall and in the data hue. */
export function EvidenceStrip({ passages, cited, activeId, onActive, onOpen }: {
  passages: Passage[]; cited: Set<string>; activeId: string | null; onActive: (id: string | null) => void; onOpen: (id: string) => void;
}) {
  return (
    <div className="strip" role="list" aria-label="Passages the answer was written from">
      {passages.map((p, i) => (
        <button
          key={p.chunk_id}
          role="listitem"
          className="tick"
          style={{ "--i": i } as React.CSSProperties}
          data-cited={cited.has(p.chunk_id)}
          data-active={activeId === p.chunk_id}
          aria-label={`${p.label}, ${p.title}${cited.has(p.chunk_id) ? ", cited in the answer" : ""}`}
          onMouseEnter={() => onActive(p.chunk_id)}
          onMouseLeave={() => onActive(null)}
          onFocus={() => onActive(p.chunk_id)}
          onBlur={() => onActive(null)}
          onClick={() => onOpen(p.chunk_id)}
        />
      ))}
    </div>
  );
}

/** The same strip, moving: shown while an answer is being written. The wave only says "working"; it is not a progress measure. */
export function SearchingStrip() {
  return (
    <div className="strip strip-wait" aria-hidden="true">
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} className="tick" style={{ "--i": i } as React.CSSProperties} />
      ))}
    </div>
  );
}

const LEVEL_LABEL = { public: "Public", internal: "Internal", restricted: "Restricted" } as const;

export function Level({ level }: { level: Passage["access_level"] }) {
  return (
    <span className="pill" data-level={level}>
      {level !== "public" && <Lock size={11} strokeWidth={1.75} aria-hidden="true" />}
      {LEVEL_LABEL[level]}
    </span>
  );
}

export function EvidencePanel({ result, activeId, openId, onActive, onOpen, scope }: {
  result: AskResult | null; activeId: string | null; openId: string | null;
  onActive: (id: string | null) => void; onOpen: (id: string | null) => void; scope: Scope;
}) {
  const passages = result?.passages ?? [];
  const cited = new Set((result?.points ?? []).flatMap((p) => p.cited));
  const sources = result?.sources ?? [];
  const searched = result && !!result.passages;

  return (
    <aside className="evidence card" aria-label="Evidence">
      <header className="card-head">
        <h2>Evidence</h2>
        {searched && <span className="muted small num">{passages.length} read, {cited.size} cited</span>}
      </header>

      {!searched ? (
        <div className="empty-frame">
          {result?.status === "blocked"
            ? "The question was stopped before any search, so nothing was read."
            : scope
              ? `Each answer shows the passages it was written from. You can read ${scope.pages.toLocaleString("en-US")} pages (${scope.chunks.toLocaleString("en-US")} passages).`
              : "Each answer shows the passages it was written from."}
        </div>
      ) : (
        <>
          <EvidenceStrip passages={passages} cited={cited} activeId={activeId} onActive={onActive} onOpen={(id) => onOpen(id)} />

          {sources.length > 0 && (
            <section aria-labelledby="sources-h">
              <h3 id="sources-h">Sources cited</h3>
              <ol className="sources">
                {sources.map((s, i) => {
                  const url = safeUrl(s.url);
                  return (
                    <li key={s.chunk_id} data-active={activeId === s.chunk_id} onMouseEnter={() => onActive(s.chunk_id)} onMouseLeave={() => onActive(null)}>
                      <span className="src-n num">{i + 1}</span>
                      <span className="src-body">
                        {url ? (
                          <Link href={url} target="_blank" rel="noopener noreferrer" className="src-title">
                            {clean(s.title)} <ExternalLink size={12} strokeWidth={1.5} aria-label="opens the documentation page" />
                          </Link>
                        ) : (
                          <span className="src-title">{clean(s.title)}</span>
                        )}
                        <span className="muted small">{PRODUCT_NAME[s.product] ?? s.product}</span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            </section>
          )}

          <section aria-labelledby="read-h">
            <h3 id="read-h">Passages read</h3>
            {passages.length === 0 ? (
              <div className="empty-frame">Nothing readable was retrieved for this account.</div>
            ) : (
              <ul className="passages">
                {passages.map((p) => {
                  const open = openId === p.chunk_id;
                  return (
                    <li key={p.chunk_id} id={`passage-${p.label}`} data-active={activeId === p.chunk_id} data-open={open}>
                      <button className="passage-head" aria-expanded={open} onClick={() => onOpen(open ? null : p.chunk_id)}
                        onMouseEnter={() => onActive(p.chunk_id)} onMouseLeave={() => onActive(null)}>
                        <span className="passage-label">{p.label}</span>
                        <span className="passage-title">{clean(p.title)}</span>
                        {cited.has(p.chunk_id) && <span className="cited-dot" title="Cited in the answer" aria-label="cited" />}
                        <ChevronDown size={14} strokeWidth={1.5} className="chev" aria-hidden="true" />
                      </button>
                      <div className="passage-body" aria-hidden={!open}>
                        <div>
                          <div className="passage-meta">
                            <span className="muted small">{PRODUCT_NAME[p.product] ?? p.product}</span>
                            <Level level={p.access_level} />
                          </div>
                          <Rich text={"```\n" + p.text.replaceAll("```", "'''") + "\n```"} />
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section aria-labelledby="ran-h">
            <h3 id="ran-h">How it ran</h3>
            <dl className="kv">
              {result.rewritten && (<><dt>Searched for</dt><dd>{clean(result.question_used)}</dd></>)}
              {result.products.length > 0 && (<><dt>Product detected</dt><dd>{result.products.map((p) => PRODUCT_NAME[p as keyof typeof PRODUCT_NAME] ?? p).join(", ")}{result.product_filter ? `, search limited to ${PRODUCT_NAME[result.product_filter as keyof typeof PRODUCT_NAME] ?? result.product_filter}` : ""}</dd></>)}
              {result.status === "answered" && (<><dt>Written by</dt><dd>{result.provider}</dd><dt>Claims checked by</dt><dd>{result.verified_by || "nothing"}</dd><dt>Covers the question</dt><dd>{result.coverage}</dd></>)}
              {result.dropped_chunks.length > 0 && (<><dt>Left out</dt><dd>{result.dropped_chunks.length} {result.dropped_chunks.length === 1 ? "passage" : "passages"} that looked like injected instructions</dd></>)}
            </dl>
          </section>
        </>
      )}
    </aside>
  );
}
