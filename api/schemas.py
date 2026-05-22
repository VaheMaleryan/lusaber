"""Lusaber · Լուսաբեր — Pydantic v2 schemas for the FastAPI service.

Defines the request/response contracts for ``/analyze``, ``/health``,
and ``/stats``. All schemas use ``model_config`` with ``extra="forbid"``
so callers get a clear 422 on unknown fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# /analyze
# ---------------------------------------------------------------------------
Verdict = Literal["LIKELY DISINFORMATION", "UNCERTAIN", "LIKELY CREDIBLE"]


class AnalyzeRequest(BaseModel):
    """Request body for ``POST /analyze``.

    At least one of ``text`` or ``url`` must be provided.
    ``title`` is optional but improves the headline-body consistency
    signal when supplied.
    """

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None,
        description="Article body in Armenian. Required if `url` is omitted.",
        min_length=1,
        max_length=200_000,
    )
    title: str | None = Field(
        default=None,
        description="Article headline. Optional; improves consistency feature.",
        max_length=1_000,
    )
    url: AnyUrl | None = Field(
        default=None,
        description="Canonical article URL. Required for source-fingerprinting signals.",
    )


class SourceAnalysisOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    in_fake_registry: bool
    is_legitimate_outlet: bool
    matched_domain: str | None
    similarity_score: float = Field(ge=0.0, le=1.0)
    brand_fragment_match: str | None
    verdict: Literal["legitimate", "known-fake", "likely-mimicry", "unknown"]
    explanation: str


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credibility_score: float = Field(
        ge=0.0,
        le=100.0,
        description="0–100, where 100 is most credible.",
    )
    verdict: Verdict
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Calibrated model confidence in the verdict.",
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="Human-readable explanations for the score.",
    )
    source_analysis: SourceAnalysisOut | None = Field(
        default=None,
        description="Per-domain signals. Null when `url` is not provided.",
    )
    processing_time_ms: float = Field(
        ge=0.0,
        description="Server-side wall clock for the request.",
    )
    model_version: str = Field(
        description="Identifier of the scoring model used.",
    )


# ---------------------------------------------------------------------------
# /summarize
# ---------------------------------------------------------------------------
DetectedLanguage = Literal["hy", "ru", "en", "mixed"]


class SummarizeRequest(BaseModel):
    """Request body for ``POST /summarize``.

    ``text`` is required — unlike ``/analyze`` we never accept
    URL-only payloads, because the summarizer needs the article body
    to actually produce a summary.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        description="Article body. Armenian preferred; Russian / English fragments tolerated.",
        min_length=20,
        max_length=200_000,
    )
    title: str | None = Field(
        default=None,
        description="Optional headline; passed to the model for better grounding.",
        max_length=1_000,
    )
    url: AnyUrl | None = Field(
        default=None,
        description="Optional canonical URL — drives the embedded source-check.",
    )


class EntitiesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    people: list[str] = Field(default_factory=list, max_length=6)
    places: list[str] = Field(default_factory=list, max_length=6)
    organizations: list[str] = Field(default_factory=list, max_length=6)


class SummarizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_hy: str = Field(description="Summary in Armenian (Հայերեն), 2–4 sentences.")
    summary_en: str = Field(description="Summary in English, 2–4 sentences.")
    headline_en: str = Field(description="One-line English headline, AP/Reuters style.")
    entities: EntitiesOut
    topics: list[str] = Field(default_factory=list, max_length=5)
    reading_time_minutes: float = Field(ge=0.0)
    language_detected: DetectedLanguage
    source_check: SourceAnalysisOut | None = Field(
        default=None,
        description="Per-domain signals; null when no URL was provided.",
    )
    processing_time_ms: float = Field(ge=0.0)
    model: str = Field(description="Anthropic model identifier used for this call.")


# ---------------------------------------------------------------------------
# /feedback
# ---------------------------------------------------------------------------
FeedbackRating = Literal[-1, 1]


class FeedbackRequest(BaseModel):
    """Request body for ``POST /feedback``.

    A ``session_id`` is a stable, opaque identifier minted by the
    frontend (e.g. a UUID stored in ``sessionStorage``). It is used
    only to de-duplicate accidental double-clicks on the thumbs in
    the same browser tab — not for authentication.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=4, max_length=128)
    rating: FeedbackRating = Field(
        description="1 for thumbs-up, -1 for thumbs-down."
    )
    summary_en: str = Field(
        min_length=1, max_length=4_000,
        description="The English summary the user is rating. Stored as a SHA-1 hash, not verbatim.",
    )
    article_length: int = Field(ge=0, le=200_000)
    topics: list[str] = Field(default_factory=list, max_length=5)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["recorded", "duplicate"]
    total_ratings: int = Field(ge=0)


class FeedbackStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_ratings: int = Field(ge=0)
    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    positive_rate: float = Field(
        ge=0.0, le=1.0,
        description="positive / total_ratings, or 0.0 if no ratings yet.",
    )
    avg_article_length: float = Field(ge=0.0)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    name: Literal["Lusaber"] = "Lusaber"
    model_version: str
    uptime_seconds: float = Field(ge=0.0)


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------
class StatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["Lusaber"] = "Lusaber"
    model_version: str
    total_analyses: int = Field(ge=0)
    uptime_seconds: float = Field(ge=0.0)
