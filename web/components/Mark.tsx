/** The product mark: three retrieved passages as ticks, one of them cited (the data hue). The same shape the evidence strip draws. */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3" y="9" width="4" height="12" rx="1" fill="var(--text)" />
      <rect x="10" y="3" width="4" height="18" rx="1" fill="var(--hue)" />
      <rect x="17" y="12" width="4" height="9" rx="1" fill="var(--text)" />
    </svg>
  );
}
