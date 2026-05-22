/**
 * Lusaber · Լուսաբեր — application root.
 *
 * After the May 2026 pivot the app is a tabbed editor:
 *
 *   • "Summarize"  (default) — Anthropic-powered bilingual summary,
 *                              entities, topics, source check.
 *   • "Source check"          — domain fingerprinting only (no score,
 *                              no verdict, no disinformation classifier).
 *
 * The disinformation classifier still lives in api/analyzer.py and the
 * /analyze endpoint still returns its full payload, but the frontend
 * has deliberately stopped surfacing the credibility score, verdict,
 * and red-flag list. Domain mimicry / known-fake checks remain visible
 * because that subsystem still works well.
 */

import React, { useCallback, useState } from "react";
import Summarizer from "./components/Summarizer.jsx";
import SourceCheck from "./components/SourceCheck.jsx";
import { friendlyError, safeReadBody } from "./lib/friendlyError.js";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const TABS = [
  { id: "summarize", label: "Summarize" },
  { id: "source", label: "Source check" },
];

// ---------------------------------------------------------------------------
// Tab strip
// ---------------------------------------------------------------------------
function TabStrip({ active, onChange }) {
  return (
    <nav
      role="tablist"
      aria-label="Lusaber modes"
      className="border-b border-paper-border bg-paper-card"
    >
      <div className="mx-auto flex max-w-page gap-6 px-4 md:px-6">
        {TABS.map((t) => {
          const isActive = active === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={isActive}
              onClick={() => onChange(t.id)}
              className={[
                "relative py-3 text-[14px] font-medium tracking-wide transition-colors duration-button",
                isActive
                  ? "text-ink"
                  : "text-ink-muted hover:text-ink",
              ].join(" ")}
            >
              {t.label}
              {isActive && (
                <span
                  className="absolute inset-x-0 -bottom-px h-[2px]"
                  style={{ backgroundColor: "#8B1A1A" }}
                  aria-hidden="true"
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Source-check tab — URL-only domain fingerprinting
// ---------------------------------------------------------------------------
function SourceCheckTab() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState(null);
  const [error, setError] = useState("");

  const onSubmit = useCallback(
    async (e) => {
      e?.preventDefault?.();
      setError("");
      if (!url.trim()) {
        setError("Provide a URL to check the source.");
        return;
      }
      setLoading(true);
      setSource(null);
      try {
        // /analyze still drives this — we just throw away the
        // credibility_score / verdict / red_flags fields and keep
        // only source_analysis. The text classifier is no longer
        // surfaced anywhere in the UI.
        const resp = await fetch(`${API_BASE}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: url.trim() }),
        });
        if (!resp.ok) {
          const body = await safeReadBody(resp);
          setError(friendlyError(resp.status, body));
          return;
        }
        const data = await resp.json();
        setSource(data.source_analysis || null);
      } catch (err) {
        setError(
          "We couldn't reach the Lusaber server. Please check your connection and try again."
        );
      } finally {
        setLoading(false);
      }
    },
    [url]
  );

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[45%_55%] md:gap-8">
      <section>
        <h2 className="serif mb-5 text-[18px]">Check a domain</h2>

        {error && (
          <div
            role="alert"
            className="mb-3 rounded-md border border-[#F1C5C5] bg-[#FCEBEB] px-3 py-2 text-[13px] text-[#991B1B]"
          >
            {error}
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="field-label" htmlFor="src-url">
              Article URL
            </label>
            <input
              id="src-url"
              type="text"
              className="field font-mono text-[14px]"
              placeholder="https://armenpress-news.com/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              spellCheck="false"
              autoComplete="off"
            />
          </div>

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Checking…" : "Ստուգել · Check source"}
          </button>

          <p className="pt-1 text-[12px] leading-relaxed text-ink-muted">
            Lusaber checks the domain against a hand-curated registry of
            known Storm-1516 / CivilNetCheck typosquats and runs a
            Levenshtein scan against verified Armenian outlets. No score
            or verdict is produced — only the source signal.
          </p>
        </form>
      </section>

      <section className="space-y-4">
        {loading ? (
          <section className="card space-y-2 p-6">
            <div className="skeleton h-5 w-40" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-3/4" />
          </section>
        ) : source ? (
          <SourceCheck source={source} />
        ) : (
          <section className="card flex flex-col items-center px-8 py-12 text-center">
            <h3 className="serif text-xl">Enter a URL to check the domain</h3>
            <p className="mt-2 max-w-md text-[14px] text-ink-muted">
              Lusaber's source-fingerprinting subsystem catches
              typosquats (e.g. <span className="font-mono">arrmenpress.am</span>),
              known-fake clones, and Western-outlet brand-mimicry
              patterns regardless of article content.
            </p>
          </section>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  const [tab, setTab] = useState("summarize");

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      {/* ===== Header ===== */}
      <header className="border-b border-paper-border bg-paper-card">
        <div className="mx-auto flex max-w-page items-center justify-between px-4 py-4 md:px-6">
          <div className="flex items-baseline gap-2">
            <span className="serif text-[24px] font-bold leading-none">
              Lusaber
            </span>
            <span className="text-[14px] text-ink-muted">· Լուսաբեր</span>
          </div>
          <span className="badge">Research prototype · v1</span>
        </div>
      </header>

      <TabStrip active={tab} onChange={setTab} />

      {/* ===== Main ===== */}
      <main className="mx-auto w-full max-w-page flex-1 px-4 py-8 md:px-6 md:py-10">
        {tab === "summarize" ? <Summarizer /> : <SourceCheckTab />}
      </main>

      {/* ===== Footer ===== */}
      <footer className="border-t border-paper-border bg-paper-card">
        <div className="mx-auto max-w-page px-4 py-6 text-[12px] leading-relaxed text-ink-muted md:px-6">
          <p>
            <span className="serif text-ink">Lusaber · Լուսաբեր</span>
            &nbsp;— Making Armenian journalism accessible to diaspora,
            journalists, and language learners.
          </p>
          <p className="mt-1">
            Built by Vahe Maleryan · 2026 · MIT License
          </p>
          <p className="mt-1">
            <a
              className="underline decoration-paper-border underline-offset-2 hover:text-armenian-red"
              href="https://www.civilnet.am"
              target="_blank"
              rel="noreferrer"
            >
              civilnet.am
            </a>
            &nbsp;·&nbsp;
            <a
              className="underline decoration-paper-border underline-offset-2 hover:text-armenian-red"
              href="https://media.am"
              target="_blank"
              rel="noreferrer"
            >
              media.am
            </a>
            &nbsp;·&nbsp;
            <a
              className="underline decoration-paper-border underline-offset-2 hover:text-armenian-red"
              href="https://infact.am"
              target="_blank"
              rel="noreferrer"
            >
              infact.am
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}
