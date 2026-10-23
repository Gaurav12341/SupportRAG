"use client";
import { ExternalLink, Lock, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { int } from "@/lib/format";
import { clean, safeUrl } from "@/lib/richtext";
import { PRODUCT_NAME, PRODUCTS, type Library, type Product, type Session } from "@/lib/types";
import { Level } from "./EvidencePanel";

const PAGE = 50;
const KIND = { docs: "Documentation", qa: "Stack Overflow Q&A" } as const;
const TYPE_LABEL: Record<string, string> = { howto: "How-to", concept: "Concept", qa: "Q&A", reference: "Reference", troubleshooting: "Troubleshooting", tutorial: "Tutorial" };

export function DocsExplorer({ library, session }: { library: Library; session: Session }) {
  const [product, setProduct] = useState<Product | "all">("all");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"" | keyof typeof KIND>("");
  const [level, setLevel] = useState("");
  const [shown, setShown] = useState(PAGE);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: library.documents.length };
    for (const d of library.documents) c[d.product] = (c[d.product] ?? 0) + 1;
    return c;
  }, [library]);
  const lockedTotal = Object.values(library.locked).reduce((a, b) => a + (b ?? 0), 0);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return library.documents.filter(
      (d) =>
        (product === "all" || d.product === product) &&
        (!kind || (kind === "qa") === (d.source === "stackoverflow")) &&
        (!level || d.access_level === level) &&
        (!q || d.title.toLowerCase().includes(q) || d.id.toLowerCase().includes(q)),
    );
  }, [library, product, query, kind, level]);

  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setShown(PAGE); };
  const levels = [...new Set(library.documents.map((d) => d.access_level))];

  return (
    <>
      <div className="count-cards" role="group" aria-label="Filter by product">
        {(["all", ...PRODUCTS] as const).map((p) => (
          <button key={p} className="count-card" aria-pressed={product === p} onClick={() => reset(setProduct)(p)}>
            <span className="label">{p === "all" ? "All products" : PRODUCT_NAME[p]}</span>
            <span className="value num">{int(counts[p] ?? 0)}</span>
            {(p === "all" ? lockedTotal : (library.locked[p] ?? 0)) > 0 && (
              <span className="sub"><Lock size={11} strokeWidth={1.75} aria-hidden="true" /> {int(p === "all" ? lockedTotal : library.locked[p]!)} locked</span>
            )}
          </button>
        ))}
      </div>

      {lockedTotal > 0 && (
        <p className="locked-note">
          <Lock size={14} strokeWidth={1.5} aria-hidden="true" />
          <span>
            {int(lockedTotal)} {lockedTotal === 1 ? "page is" : "pages are"} locked for this account and never used in its answers.{" "}
            {session.user ? "Ask an admin for a license on the product you need." : <><Link href="/login">Sign in</Link> to read what your licenses cover.</>}
          </span>
        </p>
      )}

      <section className="card table-card" aria-label="Documents">
        <div className="toolbar">
          <label className="search">
            <Search size={14} strokeWidth={1.5} aria-hidden="true" />
            <span className="sr-only">Search titles</span>
            <input type="search" placeholder="Search titles and paths" value={query} onChange={(e) => reset(setQuery)(e.target.value)} />
          </label>
          <label className="select-inline">
            <span className="sr-only">Kind</span>
            <select value={kind} onChange={(e) => reset(setKind)(e.target.value as "" | keyof typeof KIND)}>
              <option value="">All kinds</option>
              <option value="docs">{KIND.docs}</option>
              <option value="qa">{KIND.qa}</option>
            </select>
          </label>
          {levels.length > 1 && (
            <label className="select-inline">
              <span className="sr-only">Access level</span>
              <select value={level} onChange={(e) => reset(setLevel)(e.target.value)}>
                <option value="">All levels</option>
                {levels.map((l) => <option key={l} value={l}>{l[0].toUpperCase() + l.slice(1)}</option>)}
              </select>
            </label>
          )}
          <span className="small muted toolbar-count num" aria-live="polite">{int(rows.length)} {rows.length === 1 ? "page" : "pages"}</span>
        </div>

        {rows.length === 0 ? (
          <div className="empty-frame">No page matches those filters.</div>
        ) : (
          <table className="docs">
            <thead>
              <tr><th scope="col">Page</th><th scope="col" className="col-type">Type</th><th scope="col" className="col-level">Access</th><th scope="col" className="num">Passages</th></tr>
            </thead>
            <tbody>
              {rows.slice(0, shown).map((d) => {
                const url = safeUrl(d.url);
                return (
                  <tr key={d.id}>
                    <td>
                      {url ? (
                        <Link href={url} target="_blank" rel="noopener noreferrer" className="doc-title">
                          {clean(d.title)} <ExternalLink size={12} strokeWidth={1.5} aria-label="opens the original page" />
                        </Link>
                      ) : <span className="doc-title">{clean(d.title)}</span>}
                      <span className="doc-sub">{PRODUCT_NAME[d.product]} · {d.license}</span>
                    </td>
                    <td className="col-type">{d.source === "stackoverflow" ? "Q&A" : (TYPE_LABEL[d.doc_type] ?? d.doc_type)}</td>
                    <td className="col-level"><Level level={d.access_level} /></td>
                    <td className="num">{d.chunks}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {rows.length > PAGE && (
          <footer className="table-foot">
            <span className="small muted num">Showing 1–{Math.min(shown, rows.length)} of {int(rows.length)}</span>
            {shown < rows.length && <button className="btn btn-secondary btn-sm" onClick={() => setShown((s) => s + PAGE)}>Show {Math.min(PAGE, rows.length - shown)} more</button>}
          </footer>
        )}
      </section>
    </>
  );
}
