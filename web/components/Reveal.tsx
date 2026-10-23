"use client";
import { useEffect, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";

// Bars and strips draw once, the first time they scroll into view. Without script, or with reduced motion, they are simply drawn.
// data-reveal: "idle" (drawn, the server render) -> "armed" (hidden, set before the first paint) -> "in" (drawing).
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function Reveal({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null);
  useIsoLayoutEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.dataset.reveal = "armed";
    const watch = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        el.dataset.reveal = "in";
        watch.disconnect();
      },
      { threshold: 0.25 },
    );
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  return (
    <div ref={ref} className={className} style={style} data-reveal="idle">
      {children}
    </div>
  );
}
