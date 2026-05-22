/**
 * Lusaber · Լուսաբեր — Summarize tab.
 *
 * Calls `POST /summarize`, then renders three result cards:
 *
 *   1. Summaries        — English headline (serif), Armenian + English
 *                         summary panels side-by-side
 *   2. Entities         — People · Places · Organizations as pill tags
 *   3. Topics + Source  — topic pills with category-tinted backgrounds,
 *                         plus a compact source-check on the right
 *
 * Demo articles are fetched from /demo_articles.json (served from
 * frontend/public/) and listed in a collapsible "Try an example" panel.
 */

import React, { useCallback, useEffect, useState } from "react";
import SourceCheck from "./SourceCheck.jsx";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Stable opaque identifier for this browser session. Used by /feedback
// to de-duplicate accidental double-clicks — no authentication, no PII.
function getSessionId() {
  const KEY = "lusaber-session-id";
  let sid = null;
  try {
    sid = sessionStorage.getItem(KEY);
    if (!sid) {
      sid = `sid-${crypto.randomUUID()}`;
      sessionStorage.setItem(KEY, sid);
    }
  } catch {
    sid = `sid-${Math.random().toString(36).slice(2)}`;
  }
  return sid;
}

// ---------------------------------------------------------------------------
// Topic palette
// ---------------------------------------------------------------------------
const TOPIC_COLORS = {
  politics: { bg: "#FCE9E9", fg: "#8B1A1A" },
  economy: { bg: "#E7F0F4", fg: "#2C5470" },
  society: { bg: "#ECF6F0", fg: "#2D6A4F" },
  "foreign-policy": { bg: "#FDF3E2", fg: "#B45309" },
  security: { bg: "#F1E4E4", fg: "#7A1F1F" },
  defence: { bg: "#EAEAE5", fg: "#2A2A24" },
  judiciary: { bg: "#EFE6F2", fg: "#5B2A6E" },
  judicial: { bg: "#EFE6F2", fg: "#5B2A6E" },
  elections: { bg: "#F8E6E1", fg: "#9F351B" },
  media: { bg: "#E8EEF6", fg: "#3A4F73" },
  culture: { bg: "#F6E9EE", fg: "#82325E" },
  sports: { bg: "#E9F3EC", fg: "#2F6F4B" },
  health: { bg: "#E7F4F1", fg: "#1F5E55" },
  tech: { bg: "#ECEFF5", fg: "#3A4F73" },
  diaspora: { bg: "#FBEDE0", fg: "#995B1A" },
  environment: { bg: "#E9F0E2", fg: "#3F6630" },
  breaking: { bg: "#FCEBEB", fg: "#991B1B" },
};

const LANGUAGE_LABEL = {
  hy: "Armenian (Հայերեն)",
  ru: "Russian",
  en: "English",
  mixed: "Mixed",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function ErrorBanner({ message, onDismiss }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="mb-3 flex items-start justify-between gap-3 rounded-md border border-[#F1C5C5] bg-[#FCEBEB] px-3 py-2 text-[13px] text-[#991B1B]"
    >
      <span>{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-[#991B1B]/70 hover:text-[#991B1B]"
        aria-label="Dismiss error"
      >
        ×
      </button>
    </div>
  );
}

function SummariesCard({ headlineEn, summaryHy, summaryEn, language, readingTime }) {
  return (
    <section
      className="card animate-fadeRise p-6"
      style={{ animationDelay: "0ms" }}
      aria-label="summaries"
    >
      <div className="mb-4 flex items-start justify-between gap-4">
        <h3 className="serif text-[20px] font-bold leading-snug text-ink">
          {headlineEn || "Summary"}
        </h3>
        <div className="shrink-0 text-right">
          <div className="font-mono text-[11px] uppercase tracking-verdict text-ink-muted">
            {LANGUAGE_LABEL[language] || "—"}
          </div>
          <div className="font-mono text-[11px] text-ink-muted">
            {readingTime != null ? `~${readingTime} min read` : "—"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <article
          className="rounded-md border border-paper-border px-4 py-4"
          style={{ backgroundColor: "#FBF7EE" }}
          lang="hy"
        >
          <div className="mb-2 text-[11px] uppercase tracking-verdict text-ink-muted">
            Հայերեն
          </div>
          <p className="serif text-[15px] leading-relaxed text-ink">
            {summaryHy || "—"}
          </p>
        </article>

        <article
          className="rounded-md border border-paper-border bg-paper px-4 py-4"
          lang="en"
        >
          <div className="mb-2 text-[11px] uppercase tracking-verdict text-ink-muted">
            English
          </div>
          <p className="text-[15px] leading-relaxed text-ink">
            {summaryEn || "—"}
          </p>
        </article>
      </div>
    </section>
  );
}

function PillRow({ items, emptyLabel = "—" }) {
  if (!items || items.length === 0) {
    return <span className="text-[13px] text-ink-muted">{emptyLabel}</span>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <li
          key={`${item}-${i}`}
          className="rounded-full border border-paper-border bg-paper px-2.5 py-0.5 text-[12px] text-ink"
        >
          {item}
        </li>
      ))}
    </ul>
  );
}

function EntitiesCard({ entities }) {
  return (
    <section
      className="card animate-fadeRise p-6"
      style={{ animationDelay: "100ms" }}
      aria-label="entities"
    >
      <h3 className="serif mb-4 text-lg">Entities</h3>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-verdict text-ink-muted">
            People
          </div>
          <PillRow items={entities?.people || []} />
        </div>
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-verdict text-ink-muted">
            Places
          </div>
          <PillRow items={entities?.places || []} />
        </div>
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-verdict text-ink-muted">
            Organizations
          </div>
          <PillRow items={entities?.organizations || []} />
        </div>
      </div>
    </section>
  );
}

function TopicPills({ topics }) {
  if (!topics || topics.length === 0) {
    return <span className="text-[13px] text-ink-muted">—</span>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {topics.map((t, i) => {
        const c = TOPIC_COLORS[t] || { bg: "#F1EFEA", fg: "#1A1917" };
        return (
          <li
            key={`${t}-${i}`}
            className="rounded-full px-2.5 py-0.5 text-[12px] font-medium"
            style={{ backgroundColor: c.bg, color: c.fg }}
          >
            {t}
          </li>
        );
      })}
    </ul>
  );
}

function TopicsAndSourceCard({ topics, source, processingTimeMs, model }) {
  return (
    <section
      className="card animate-fadeRise p-6"
      style={{ animationDelay: "200ms" }}
      aria-label="topics-and-source"
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <h3 className="serif mb-4 text-lg">Topics</h3>
          <TopicPills topics={topics} />
          <footer className="mt-5 font-mono text-[11px] text-ink-muted">
            Processed in {Math.round(processingTimeMs || 0)} ms · {model || "—"}
          </footer>
        </div>

        <div>
          <h3 className="serif mb-4 text-lg">Source</h3>
          {source ? (
            <SourceSummary source={source} />
          ) : (
            <p className="text-[13px] text-ink-muted">
              No URL supplied — domain check skipped.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * Compact inline source summary (different from the full SourceCheck card —
 * we render it inside the combined Topics+Source card without the heading
 * or warning banner).
 */
function SourceSummary({ source }) {
  const VERDICT_PILLS = {
    legitimate: { bg: "#ECF6F0", color: "#2D6A4F", label: "Legitimate" },
    unknown: { bg: "#F2F0EB", color: "#6B6860", label: "Unknown" },
    "likely-mimicry": { bg: "#FDF3E2", color: "#B45309", label: "Likely mimicry" },
    "known-fake": { bg: "#FCEBEB", color: "#991B1B", label: "Known fake" },
  };
  const pill = VERDICT_PILLS[source.verdict] || VERDICT_PILLS.unknown;
  return (
    <dl className="space-y-2 text-[13px]">
      <div className="flex items-center justify-between gap-3">
        <dt className="text-ink-muted">Domain</dt>
        <dd className="font-mono text-ink">{source.domain || "—"}</dd>
      </div>
      <div className="flex items-center justify-between gap-3">
        <dt className="text-ink-muted">Verdict</dt>
        <dd>
          <span
            className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px] uppercase tracking-verdict"
            style={{ backgroundColor: pill.bg, color: pill.color }}
          >
            {pill.label}
          </span>
        </dd>
      </div>
      {source.matched_domain && (
        <div className="flex items-center justify-between gap-3">
          <dt className="text-ink-muted">Mimics</dt>
          <dd className="font-mono text-ink">{source.matched_domain}</dd>
        </div>
      )}
    </dl>
  );
}

function FeedbackBar({ result }) {
  // `key` is recomputed when the result changes, so the bar resets
  // for each new summary. Internally tracked via state.
  const [submitted, setSubmitted] = useState(null); // null | 1 | -1
  const [pending, setPending] = useState(false);
  const [stats, setStats] = useState(null);

  // Pull the latest aggregate stats once on first render.
  useEffect(() => {
    fetch(`${API_BASE}/feedback/stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setStats(data))
      .catch(() => {
        /* non-fatal */
      });
  }, []);

  const submit = useCallback(
    async (rating) => {
      if (submitted || pending) return;
      setPending(true);
      try {
        const resp = await fetch(`${API_BASE}/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: getSessionId(),
            rating,
            summary_en: result.summary_en || "",
            article_length: (result.reading_time_minutes || 0) * 200, // best-effort
            topics: result.topics || [],
          }),
        });
        if (resp.ok) {
          setSubmitted(rating);
          // Refresh aggregate so the user immediately sees their vote
          // reflected (or the duplicate count stays stable).
          fetch(`${API_BASE}/feedback/stats`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => data && setStats(data))
            .catch(() => {});
        }
      } catch {
        /* swallow — feedback is best-effort */
      } finally {
        setPending(false);
      }
    },
    [result, submitted, pending]
  );

  const positivePct =
    stats && stats.total_ratings > 0
      ? Math.round(stats.positive_rate * 100)
      : null;

  return (
    <section
      className="card animate-fadeRise p-5"
      style={{ animationDelay: "300ms" }}
      aria-label="feedback"
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          {submitted == null ? (
            <p className="text-[14px] text-ink">
              Was this summary accurate?
            </p>
          ) : (
            <p className="text-[14px] font-medium text-ink">
              Thank you for your feedback!
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={pending || submitted != null}
            onClick={() => submit(1)}
            className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors duration-button disabled:cursor-not-allowed disabled:opacity-90"
            style={{
              borderColor: submitted === 1 ? "#2D6A4F" : "#E8E6E1",
              backgroundColor: submitted === 1 ? "#ECF6F0" : "#FFFFFF",
              color: submitted === 1 ? "#2D6A4F" : "#1A1917",
            }}
            aria-pressed={submitted === 1}
          >
            <span aria-hidden="true">👍</span>
            <span>Yes</span>
          </button>
          <button
            type="button"
            disabled={pending || submitted != null}
            onClick={() => submit(-1)}
            className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors duration-button disabled:cursor-not-allowed disabled:opacity-90"
            style={{
              borderColor: submitted === -1 ? "#991B1B" : "#E8E6E1",
              backgroundColor: submitted === -1 ? "#FCEBEB" : "#FFFFFF",
              color: submitted === -1 ? "#991B1B" : "#1A1917",
            }}
            aria-pressed={submitted === -1}
          >
            <span aria-hidden="true">👎</span>
            <span>No</span>
          </button>
        </div>
      </div>

      {stats && stats.total_ratings > 0 && (
        <p className="mt-3 font-mono text-[11px] text-ink-muted">
          {stats.total_ratings} {stats.total_ratings === 1 ? "person has" : "people have"} rated summaries ·{" "}
          {positivePct}% found them accurate
        </p>
      )}
    </section>
  );
}


// ---------------------------------------------------------------------------
// Loading / Empty
// ---------------------------------------------------------------------------
function ResultsSkeleton() {
  return (
    <div className="space-y-4">
      <section className="card space-y-3 p-6">
        <div className="skeleton h-6 w-3/4" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-2 rounded-md p-3" style={{ backgroundColor: "#FBF7EE" }}>
            <div className="skeleton h-3 w-12" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-5/6" />
            <div className="skeleton h-4 w-4/6" />
          </div>
          <div className="space-y-2 rounded-md bg-paper p-3">
            <div className="skeleton h-3 w-12" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-5/6" />
            <div className="skeleton h-4 w-4/6" />
          </div>
        </div>
      </section>
      <section className="card space-y-2 p-6">
        <div className="skeleton h-5 w-32" />
        <div className="flex gap-2">
          <div className="skeleton h-5 w-20" />
          <div className="skeleton h-5 w-24" />
          <div className="skeleton h-5 w-16" />
        </div>
      </section>
      <section className="card space-y-2 p-6">
        <div className="skeleton h-5 w-40" />
        <div className="skeleton h-4 w-full" />
      </section>
    </div>
  );
}

function EmptyState() {
  return (
    <section className="card flex flex-col items-center px-8 py-12 text-center">
      <svg
        viewBox="0 0 200 60"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        className="h-16 w-full text-paper-border"
      >
        <rect x="20" y="10" width="160" height="40" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <line x1="30" y1="20" x2="170" y2="20" stroke="currentColor" strokeWidth="1.2" />
        <line x1="30" y1="28" x2="160" y2="28" stroke="currentColor" strokeWidth="1.2" />
        <line x1="30" y1="36" x2="150" y2="36" stroke="currentColor" strokeWidth="1.2" />
        <line x1="30" y1="44" x2="130" y2="44" stroke="currentColor" strokeWidth="1.2" />
      </svg>
      <h3 className="serif mt-6 text-xl">
        Paste an Armenian article to summarize
      </h3>
      <p className="mt-2 max-w-md text-[14px] text-ink-muted">
        Lusaber reads Armenian (or Russian) news and returns a faithful
        bilingual summary, named entities, topic tags, and a domain
        check — built for diaspora readers, foreign desks, and language
        learners.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function Summarizer() {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const [examplesOpen, setExamplesOpen] = useState(false);
  const [examples, setExamples] = useState([]);

  // Demo articles are fetched lazily the first time the user opens the
  // disclosure (cheap — file is ~33 KB).
  useEffect(() => {
    if (!examplesOpen || examples.length > 0) return;
    fetch("/demo_articles.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.articles) setExamples(data.articles);
      })
      .catch(() => {
        /* non-fatal — disclosure stays empty */
      });
  }, [examplesOpen, examples.length]);

  const onSubmit = useCallback(
    async (e) => {
      e?.preventDefault?.();
      setError("");
      if (!text.trim()) {
        setError("Paste an article body to summarize.");
        return;
      }
      const payload = { text: text.trim() };
      if (url.trim()) payload.url = url.trim();
      if (title.trim()) payload.title = title.trim();

      setLoading(true);
      setResult(null);
      try {
        const resp = await fetch(`${API_BASE}/summarize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (resp.status === 503) {
          setError(
            "Lusaber summarizer is offline — ANTHROPIC_API_KEY is not set on the server."
          );
          return;
        }
        if (resp.status === 429) {
          setError(
            "Rate limit exceeded (10 req/min). Wait a moment and retry."
          );
          return;
        }
        if (!resp.ok) {
          const detail = await resp.text();
          setError(
            `API returned ${resp.status}: ${detail.slice(0, 200) || "unknown"}`
          );
          return;
        }
        setResult(await resp.json());
      } catch (err) {
        setError(
          "Cannot reach the Lusaber API. Start it with: " +
            "uvicorn api.main:app --reload --port 8000"
        );
      } finally {
        setLoading(false);
      }
    },
    [text, url, title]
  );

  const fillExample = useCallback((ex) => {
    setText(ex.body);
    setUrl(ex.url || "");
    setTitle(ex.title || "");
    setError("");
  }, []);

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[45%_55%] md:gap-8">
      {/* ----- Form ----- */}
      <section>
        <h2 className="serif mb-5 text-[18px]">Summarize article</h2>

        <ErrorBanner message={error} onDismiss={() => setError("")} />

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="field-label" htmlFor="sum-text">
              Article text
            </label>
            <textarea
              id="sum-text"
              className="field min-h-[220px] resize-y leading-relaxed"
              placeholder="Տեղադրեք հայերեն հոդվածի տեքստը..."
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label" htmlFor="sum-url">
              URL <span className="text-ink-muted/70 normal-case tracking-normal">(optional)</span>
            </label>
            <input
              id="sum-url"
              type="text"
              className="field font-mono text-[14px]"
              placeholder="https://armenpress.am/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              spellCheck="false"
              autoComplete="off"
            />
          </div>

          <div>
            <label className="field-label" htmlFor="sum-title">
              Headline <span className="text-ink-muted/70 normal-case tracking-normal">(optional)</span>
            </label>
            <input
              id="sum-title"
              type="text"
              className="field"
              placeholder="Վերնագիր ..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Summarizing…" : "Ամփոփել · Summarize"}
          </button>

          <p className="pt-1 text-[12px] leading-relaxed text-ink-muted">
            Research prototype. Lusaber summarises faithfully — but
            always verify with the original source before publishing.
          </p>
        </form>

        {/* Examples disclosure */}
        <div className="mt-6 border-t border-paper-border pt-5">
          <button
            type="button"
            onClick={() => setExamplesOpen((v) => !v)}
            className="flex w-full items-center justify-between text-[13px] uppercase tracking-verdict text-ink-muted hover:text-ink"
            aria-expanded={examplesOpen}
          >
            <span>Try a real Armenian article</span>
            <span aria-hidden="true">{examplesOpen ? "−" : "+"}</span>
          </button>
          {examplesOpen && (
            <ul className="mt-3 space-y-2">
              {examples.length === 0 ? (
                <li className="text-[12px] text-ink-muted">
                  Loading demo articles…
                </li>
              ) : (
                examples.map((ex) => (
                  <li key={ex.id}>
                    <button
                      type="button"
                      className="w-full rounded-md border border-paper-border bg-paper-card px-3 py-2 text-left text-[13px] transition-colors duration-button hover:border-armenian-red"
                      onClick={() => fillExample(ex)}
                    >
                      <span className="font-mono text-[11px] uppercase tracking-verdict text-ink-muted">
                        [{ex.language}] {ex.category}
                      </span>
                      <span className="block text-ink">{ex.title}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
      </section>

      {/* ----- Results ----- */}
      <section className="space-y-4">
        {loading ? (
          <ResultsSkeleton />
        ) : result ? (
          <>
            <SummariesCard
              headlineEn={result.headline_en}
              summaryHy={result.summary_hy}
              summaryEn={result.summary_en}
              language={result.language_detected}
              readingTime={result.reading_time_minutes}
            />
            <EntitiesCard entities={result.entities} />
            <TopicsAndSourceCard
              topics={result.topics}
              source={result.source_check}
              processingTimeMs={result.processing_time_ms}
              model={result.model}
            />
            <FeedbackBar key={result.headline_en || result.summary_en} result={result} />
          </>
        ) : (
          <EmptyState />
        )}
      </section>
    </div>
  );
}
