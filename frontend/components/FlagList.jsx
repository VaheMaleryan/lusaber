/**
 * Lusaber · Լուսաբեր — red-flag list.
 *
 * Empty state shows a green check + reassuring copy. Otherwise each
 * flag is rendered with a red dot, the flag text, and a hairline
 * divider. Footer prints the model version (mono, muted).
 */

import React from "react";

export default function FlagList({ flags = [], modelVersion }) {
  const hasFlags = flags.length > 0;

  return (
    <section
      className="card animate-fadeRise p-6"
      style={{ animationDelay: "200ms" }}
      aria-label="signals-detected"
    >
      <h3 className="serif mb-4 text-lg">Signals detected</h3>

      {hasFlags ? (
        <ul className="divide-y divide-paper-border">
          {flags.map((flag, idx) => (
            <li key={idx} className="flex items-start gap-3 py-2.5">
              <span
                className="mt-2 inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: "#991B1B" }}
                aria-hidden="true"
              />
              <span className="text-[14px] leading-snug text-ink">{flag}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex items-start gap-3 rounded-md border border-paper-border bg-paper px-3 py-3">
          <span
            className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-white"
            style={{ backgroundColor: "#2D6A4F" }}
            aria-hidden="true"
          >
            ✓
          </span>
          <span className="text-[14px] text-ink">No red flags detected.</span>
        </div>
      )}

      <footer className="mt-5 flex justify-between font-mono text-[12px] text-ink-muted">
        <span>Model: {modelVersion || "—"}</span>
        <span>{flags.length} signal{flags.length === 1 ? "" : "s"}</span>
      </footer>
    </section>
  );
}
