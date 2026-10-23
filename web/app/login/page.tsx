import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { LoginForm } from "@/components/LoginForm";
import { Mark } from "@/components/Mark";
import { Reveal } from "@/components/Reveal";
import { OutcomeBar, OUTCOMES } from "@/components/OutcomeBar";
import { int, pct } from "@/lib/format";
import { getSession, load } from "@/lib/server";
import type { Metrics } from "@/lib/types";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ expired?: string }> }) {
  const { expired } = await searchParams;
  const { session } = await getSession();
  if (session.user) redirect("/");
  const metrics = await load<Metrics>("/metrics");
  const h = metrics?.holdout;

  return (
    <div className="login">
      <section className="login-form-side" aria-labelledby="signin">
        <div className="login-brand">
          <Mark size={26} />
          <span className="wordmark">SupportRAG</span>
        </div>
        <div className="login-card">
          <h1 id="signin">Sign in</h1>
          <p className="muted">Members and admins read the documents their licenses cover. Without signing in you can ask about the public documentation only.</p>
          {expired && (
            <p className="notice" role="status">Your session ended. Sign in again to continue.</p>
          )}
          <LoginForm />
        </div>
        <p className="small muted">Users, roles and access levels are simulated on public documentation. Passwords are stored only as salted, peppered scrypt hashes.</p>
      </section>

      <aside className="login-proof" aria-label="Latest evaluation">
        {h ? (
          <Reveal className="proof">
            <p className="muted">Latest result on {h.n} held-out questions</p>
            <p className="proof-figure num">{pct(h.accuracy)}</p>
            <p className="proof-line">
              {int(h.correct)} of {int(h.n)} questions answered correctly, or correctly refused. 95% interval {pct(h.ci95[0])} to {pct(h.ci95[1])}.
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
            <p className="small muted">When the documentation has no fix, it says so: {h.outcomes.correctly_refused} of {h.unanswerable} such questions were refused.</p>
          </Reveal>
        ) : (
          <div className="empty-frame">The evaluation results could not be loaded.</div>
        )}
      </aside>
    </div>
  );
}
