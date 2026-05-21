/**
 * Lusaber · Լուսաբեր — credibility score card.
 *
 * 120px circle with the score number in IBM Plex Mono, verdict label,
 * confidence bar, processing-time footer. The score animates from 0 to
 * its final value over 600 ms using requestAnimationFrame (ease-out).
 */

import React, { useEffect, useRef, useState } from "react";

const VERDICT_STYLES = {
  "LIKELY CREDIBLE": {
    color: "#2D6A4F",
    label: "Credible",
    pillBg: "#ECF6F0",
  },
  UNCERTAIN: {
    color: "#B45309",
    label: "Uncertain",
    pillBg: "#FDF3E2",
  },
  "LIKELY DISINFORMATION": {
    color: "#991B1B",
    label: "Disinformation",
    pillBg: "#FCEBEB",
  },
};

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

function useCountUp(target, duration = 600) {
  const [value, setValue] = useState(0);
  const rafRef = useRef(null);

  useEffect(() => {
    if (target == null) return;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      setValue(target * easeOutCubic(t));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setValue(target);
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration]);

  return value;
}

export default function ScoreCard({
  score,
  verdict,
  confidence,
  processingTimeMs,
  modelVersion,
}) {
  const animated = useCountUp(score ?? 0);
  const style = VERDICT_STYLES[verdict] || VERDICT_STYLES.UNCERTAIN;
  const confPct = Math.round((confidence ?? 0) * 100);

  return (
    <section
      className="card animate-fadeRise p-6"
      style={{ animationDelay: "0ms" }}
      aria-label="credibility-score"
    >
      <header className="mb-4 flex items-baseline justify-between">
        <h3 className="serif text-lg">Credibility</h3>
        <span className="font-mono text-[11px] uppercase tracking-verdict text-ink-muted">
          {modelVersion}
        </span>
      </header>

      <div className="flex items-center gap-6">
        {/* 120px circle */}
        <div
          className="relative flex h-[120px] w-[120px] shrink-0 items-center justify-center rounded-full bg-paper-card"
          style={{
            border: `3px solid ${style.color}`,
            boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
          }}
        >
          <span
            className="font-mono text-[48px] leading-none tabular-nums"
            style={{ color: style.color }}
            aria-live="polite"
            aria-label={`credibility score ${score}`}
          >
            {Math.round(animated)}
          </span>
        </div>

        {/* Verdict + confidence */}
        <div className="min-w-0 flex-1">
          <span
            className="inline-flex items-center rounded-full px-3 py-1 text-[13px] font-medium uppercase tracking-verdict"
            style={{ color: style.color, backgroundColor: style.pillBg }}
          >
            {verdict}
          </span>

          <div className="mt-4">
            <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-verdict text-ink-muted">
              <span>Confidence</span>
              <span className="font-mono tabular-nums">{confPct}%</span>
            </div>
            <div
              className="h-1 w-full overflow-hidden rounded-full bg-paper-border"
              role="progressbar"
              aria-valuenow={confPct}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-full rounded-full transition-[width] duration-500 ease-out"
                style={{
                  width: `${confPct}%`,
                  backgroundColor: style.color,
                }}
              />
            </div>
          </div>
        </div>
      </div>

      <footer className="mt-5 flex justify-end font-mono text-[11px] text-ink-muted">
        Processed in {Math.round(processingTimeMs)} ms
      </footer>
    </section>
  );
}
