/**
 * Lusaber · Լուսաբեր — source / domain panel.
 *
 * Key-value table showing the host's verdict, the legit outlet it
 * mimics (if any), Levenshtein similarity (highlighted red when
 * > 75%), and registry membership. A warning banner sits above the
 * table when the verdict is `known-fake` or `likely-mimicry`.
 */

import React from "react";

const VERDICT_PILLS = {
  legitimate: { bg: "#ECF6F0", color: "#2D6A4F", label: "Legitimate" },
  unknown: { bg: "#F2F0EB", color: "#6B6860", label: "Unknown" },
  "likely-mimicry": { bg: "#FDF3E2", color: "#B45309", label: "Likely mimicry" },
  "known-fake": { bg: "#FCEBEB", color: "#991B1B", label: "Known fake" },
};

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-3 gap-3 border-b border-paper-border py-2 last:border-b-0">
      <dt className="text-[12px] uppercase tracking-verdict text-ink-muted">
        {label}
      </dt>
      <dd className="col-span-2 font-mono text-[13px] text-ink">{children}</dd>
    </div>
  );
}

export default function SourceCheck({ source }) {
  if (!source) return null;
  const pill = VERDICT_PILLS[source.verdict] || VERDICT_PILLS.unknown;
  const sim = source.similarity_score ?? 0;
  const simPct = Math.round(sim * 100);
  const simRed = sim > 0.75;
  const showBanner =
    source.verdict === "known-fake" || source.verdict === "likely-mimicry";

  return (
    <section
      className="card animate-fadeRise p-6"
      style={{ animationDelay: "100ms" }}
      aria-label="source-analysis"
    >
      <h3 className="serif mb-4 text-lg">Source analysis</h3>

      {showBanner && (
        <div
          className="mb-4 flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]"
          style={{
            borderColor:
              source.verdict === "known-fake" ? "#F1C5C5" : "#F0D9A8",
            backgroundColor: pill.bg,
            color: pill.color,
          }}
          role="alert"
        >
          <span aria-hidden="true">⚠</span>
          <span>{source.explanation}</span>
        </div>
      )}

      <dl>
        <Row label="Domain">{source.domain || "—"}</Row>
        <Row label="Verdict">
          <span
            className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px] uppercase tracking-verdict"
            style={{ backgroundColor: pill.bg, color: pill.color }}
          >
            {pill.label}
          </span>
        </Row>
        <Row label="Mimics">
          {source.matched_domain || source.brand_fragment_match || "—"}
        </Row>
        <Row label="Similarity">
          <span
            className="tabular-nums"
            style={{ color: simRed ? "#991B1B" : "#1A1917" }}
          >
            {simPct}%
          </span>
        </Row>
        <Row label="Registry">
          {source.in_fake_registry ? "Known-fake (Lusaber registry)" : "—"}
        </Row>
      </dl>
    </section>
  );
}
