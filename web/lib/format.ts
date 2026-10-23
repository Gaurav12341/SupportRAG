const nf = new Intl.NumberFormat("en-US");
export const int = (n: number) => nf.format(n);
/** 0.7894 -> "78.9%" (percentages use one decimal everywhere). */
export const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
export const dec = (x: number, digits = 3) => x.toFixed(digits);

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
/** Seconds since the epoch -> "2 minutes ago". Call only on the client (it depends on the clock). */
export function ago(epochSeconds: number, now = Date.now()): string {
  const s = Math.round(epochSeconds - now / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of units) if (Math.abs(s) >= size) return rtf.format(Math.round(s / size), unit);
  return "just now";
}

export const stamp = (epochSeconds: number) =>
  new Date(epochSeconds * 1000).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
