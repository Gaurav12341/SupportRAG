import { parse } from "@/lib/richtext";

/** Model or document text as paragraphs, inline code and code blocks. Never links, images or HTML (see lib/richtext.ts). */
export function Rich({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className}>
      {parse(text).map((b, i) =>
        b.kind === "code" ? (
          <pre key={i} className="code"><code>{b.text}</code></pre>
        ) : (
          <p key={i}>
            {b.pieces.map((p, j) =>
              p.kind === "code" ? <code key={j}>{p.text}</code> : p.kind === "bold" ? <strong key={j}>{p.text}</strong> : <span key={j}>{p.text}</span>,
            )}
          </p>
        ),
      )}
    </div>
  );
}
