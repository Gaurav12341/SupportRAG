import type { Metrics } from "@/lib/types";

type Outcomes = NonNullable<Metrics["holdout"]>["outcomes"];

/** One entry per outcome, in drawing order. The same keys style the bar segments and the legend swatches (globals.css, [data-kind]). */
export const OUTCOMES: { key: keyof Outcomes; label: string }[] = [
  { key: "correct", label: "Answered correctly" },
  { key: "correctly_refused", label: "Correctly refused" },
  { key: "partial", label: "Partly correct" },
  { key: "incorrect", label: "Answered wrongly" },
  { key: "false_refusal", label: "Refused, but the docs had the answer" },
];

/** A 100% stacked bar, 2px seams, widths in proportion to counts. Revealed left to right by its Reveal parent. */
export function OutcomeBar({ outcomes }: { outcomes: Outcomes }) {
  return (
    <div className="outcome-bar" role="img" aria-label={OUTCOMES.map((o) => `${o.label} ${outcomes[o.key]}`).join(", ")}>
      {OUTCOMES.filter((o) => outcomes[o.key] > 0).map((o) => (
        <span key={o.key} className="seg" data-kind={o.key} style={{ flexGrow: outcomes[o.key] }} />
      ))}
    </div>
  );
}
