import type { Metadata } from "next";
import { OutcomeBar, OUTCOMES } from "@/components/OutcomeBar";
import { Reveal } from "@/components/Reveal";
import { dec, int, pct } from "@/lib/format";
import { load } from "@/lib/server";
import type { Metrics } from "@/lib/types";

export const metadata: Metadata = { title: "Evaluation" };

const TYPE_NAME: Record<string, string> = {
  error_message: "Exact error messages",
  symptom: "Symptoms",
  version: "Version questions",
  cross_product: "Questions across two products",
  unanswerable: "No documented fix (should be refused)",
};
const FAILURE_NAME: Record<string, string> = {
  retrieval_miss: "The right page was not retrieved",
  generation_error: "The writer got it wrong or incomplete",
  unsafe_or_wrong_claim: "A wrong or dangerous claim reached the answer",
};
const bar = (w: number) => ({ "--w": w }) as React.CSSProperties;

export default async function EvaluationPage() {
  const m = await load<Metrics>("/metrics");
  const h = m?.holdout;
  if (!m || !h) {
    return (
      <>
        <div className="title-row"><div><h1>Evaluation</h1></div></div>
        <div className="empty-frame">The evaluation results could not be loaded. Run <code>python -m eval.accuracy</code>, or check that the API is running.</div>
      </>
    );
  }

  const types = [...h.by_type].sort((a, b) => a.correct / a.n - b.correct / b.n);
  const weakest = [...h.by_type].filter((t) => t.type !== "unanswerable").sort((a, b) => a.correct / a.n - b.correct / b.n)[0];
  const failureTotal = Object.values(h.failures).reduce((a, b) => a + b, 0);
  const s = m.safety;
  const first = m.safety_first_run;

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Evaluation</h1>
          <p className="subline">
            {pct(h.accuracy)} of {h.n} held-out questions handled correctly. Weakest: {TYPE_NAME[weakest.type].toLowerCase()}, {weakest.correct} of {weakest.n} correct.
            Every number here is read from <code>eval/results/</code>.
          </p>
        </div>
      </div>

      <div className="eval-grid">
        <div className="stack">
          <Reveal className="card pad">
            <h2>Accuracy on the holdout</h2>
            <p className="muted small">{h.answerable} answerable and {h.unanswerable} unanswerable questions, run once with the pipeline frozen</p>
            <p className="lead-figure num">{pct(h.accuracy)}</p>
            <p className="muted">
              {h.correct} of {h.n} correct. 95% interval {pct(h.ci95[0])} to {pct(h.ci95[1])}.
            </p>
            <OutcomeBar outcomes={h.outcomes} />
            <ul className="legend-table">
              {OUTCOMES.map((o) => (
                <li key={o.key}>
                  <span className="swatch" data-kind={o.key} aria-hidden="true" />
                  <span>{o.label}</span>
                  <span className="num">{h.outcomes[o.key]}</span>
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal className="card pad">
            <h2>How accuracy got here</h2>
            <p className="muted small">Accuracy with the claim check on, each setup on its own question set</p>
            <ul className="barlist progress">
              {m.progress.map((p) => (
                <li key={p.file} data-current={p.current}>
                  <span className="barlist-label">
                    {p.label}
                    <span className="muted small"> {p.n} questions{p.current ? ", the pipeline today" : ""}</span>
                  </span>
                  <span className="track"><span className="fill" style={bar(p.accuracy)} /></span>
                  <span className="num barlist-value">
                    {pct(p.accuracy)}
                    <span className="muted small"> {pct(p.ci95[0], 0)}–{pct(p.ci95[1], 0)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal className="card pad">
            <h2>Retrieval</h2>
            <p className="muted small">
              {m.retrieval[0]?.n} answerable tuning questions, top 10 passages; one question moves recall by {dec(100 / (m.retrieval[0]?.n ?? 1), 1)} points
            </p>
            <table className="plain">
              <thead>
                <tr>
                  <th scope="col">Setup</th><th scope="col" className="num">Recall@5</th><th scope="col" className="num">Recall@10</th>
                  <th scope="col" className="num">MRR</th><th scope="col" className="num">Search</th>
                </tr>
              </thead>
              <tbody>
                {m.retrieval.map((r) => (
                  <tr key={r.file}>
                    <td>{r.label}</td>
                    <td className="num">{dec(r.recall5)}</td><td className="num">{dec(r.recall10)}</td><td className="num">{dec(r.mrr)}</td>
                    <td className="num">{r.median_ms == null ? <span className="muted">—</span> : `${int(r.median_ms)} ms`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small note">
              Search time is the median of one search on CPU after warm-up. Reranking was left off: it added about {int(Math.round(((m.retrieval[2]?.median_ms ?? 0) - (m.retrieval[1]?.median_ms ?? 0)) / 100) * 100)} ms
              per search for no clear gain in MRR.
            </p>
          </Reveal>
        </div>

        <div className="stack">
          <Reveal className="card pad">
            <h2>Where it is right and where it fails</h2>
            <p className="muted small">Correct answers (or correct refusals) by question type, lowest first</p>
            <ul className="barlist">
              {types.map((t) => (
                <li key={t.type}>
                  <span className="barlist-label">{TYPE_NAME[t.type] ?? t.type}</span>
                  <span className="track"><span className="fill" style={bar(t.correct / t.n)} /></span>
                  <span className="num barlist-value">{t.correct} of {t.n}</span>
                </li>
              ))}
            </ul>
            <h3>Why the {failureTotal} wrong ones went wrong</h3>
            <ul className="plain-rows">
              {Object.entries(h.failures).map(([k, v]) => (
                <li key={k}><span>{FAILURE_NAME[k] ?? k}</span><span className="num">{v}</span></li>
              ))}
            </ul>
            <p className="muted small">
              The evidence was fully inside the context for {h.evidence_in_context} of {h.answerable} answerable questions. {h.wrong_claim_shown} shown answers held a wrong or dangerous claim.
            </p>
          </Reveal>

          {s && (
            <Reveal className="card pad">
              <h2>Input safety</h2>
              <p className="muted small">Rule-based guard on {s.attacks} attack prompts and {s.normal} normal questions, and the scan of retrieved passages</p>
              <div className="figures">
                <Figure label="Attacks blocked" value={`${s.attacks_blocked} of ${s.attacks}`} before={first && `${first.attacks_blocked} of ${first.attacks} on the first run`} />
                <Figure label="Normal questions wrongly blocked" value={`${s.normal_blocked} of ${s.normal}`} before={first && `${first.normal_blocked} of ${first.normal} on the first run`} />
                <Figure label="Poisoned passages caught" value={`${s.poisoned_caught} of ${s.poisoned}`} before={`${s.real_chunks_flagged} of ${int(s.real_chunks)} real passages flagged`} />
              </div>
              {first && (
                <p className="muted small">The rules were fixed on these same prompts after the first run, so the second result overstates how the guard handles an attack it has not seen.</p>
              )}
            </Reveal>
          )}

          <Reveal className="card pad">
            <h2>What the holdout run used</h2>
            <dl className="kv wide">
              <dt>Embeddings</dt><dd>{h.setup.embedding}</dd>
              <dt>Passages given to the writer</dt><dd className="num">{h.setup.k_context}</dd>
              <dt>Claim check</dt><dd>{h.setup.verifier}</dd>
              <dt>Judge</dt><dd>{h.setup.judge}</dd>
            </dl>
            <table className="plain tokens">
              <thead><tr><th scope="col">Model</th><th scope="col" className="num">Calls</th><th scope="col" className="num">Tokens</th></tr></thead>
              <tbody>
                {Object.entries(h.tokens).map(([name, t]) => (
                  <tr key={name}><td>{name.replace(/^groq\//, "")}</td><td className="num">{t.calls}</td><td className="num">{int(t.total)}</td></tr>
                ))}
              </tbody>
            </table>
          </Reveal>
        </div>
      </div>

      <p className="notice" role="note">
        Treat these as small-sample numbers. With {h.n} questions, one question moves accuracy by {(100 / h.n).toFixed(1)} points. The questions, key points and
        judge labels were written and checked by an AI assistant, not by a person. The accuracy figures cover retrieval, answering and the claim check, not the sign-in, input guard or follow-up rewrite.
      </p>
    </>
  );
}

function Figure({ label, value, before }: { label: string; value: string; before?: string | null }) {
  return (
    <div className="figure">
      <span className="label">{label}</span>
      <span className="value num">{value}</span>
      {before && <span className="sub muted small">{before}</span>}
    </div>
  );
}
