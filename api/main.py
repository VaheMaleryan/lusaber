"""Lusaber · Լուսաբեր — FastAPI app entry point.

Endpoints
---------
* ``POST /analyze`` — score a text (and optionally a URL) for credibility.
* ``GET  /health``  — liveness + model-version probe.
* ``GET  /stats``   — analyses run, model version, uptime.
* ``GET  /docs``    — OpenAPI Swagger UI.

Cross-cutting
-------------
* CORS allowed for ``http://localhost:5173`` and the production frontend.
* Rate-limited to 30 requests/min/IP via ``slowapi``.
* All responses include ``x-powered-by: Lusaber``.
* Stats are persisted to ``api/lusaber.db`` (SQLite, single counter row).

Run::

    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.analyzer import Analyzer, HeuristicScorer, TrainedModelScorer
from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    EntitiesOut,
    HealthResponse,
    SourceAnalysisOut,
    StatsResponse,
    SummarizeRequest,
    SummarizeResponse,
)
from api.summarizer import (
    SummarizerFailed,
    SummarizerUnavailable,
    Summarizer,
)

logger = logging.getLogger("lusaber.api")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_API_DIR = Path(__file__).resolve().parent
_DB_PATH = Path(os.environ.get("LUSABER_DB", _API_DIR / "lusaber.db"))
_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "LUSABER_CORS_ORIGINS",
        "http://localhost:5173,https://lusaber.app",
    ).split(",")
    if o.strip()
]


# ---------------------------------------------------------------------------
# SQLite stats counter
# ---------------------------------------------------------------------------
def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS stats ("
            "  key TEXT PRIMARY KEY,"
            "  value INTEGER NOT NULL"
            ")"
        )
        con.execute(
            "INSERT OR IGNORE INTO stats(key, value) VALUES ('total_analyses', 0)"
        )
        con.commit()
    finally:
        con.close()


def _bump_total_analyses(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            "UPDATE stats SET value = value + 1 WHERE key = 'total_analyses'"
        )
        con.commit()
    finally:
        con.close()


def _get_total_analyses(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        cur = con.execute("SELECT value FROM stats WHERE key='total_analyses'")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_STARTED_AT: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _STARTED_AT
    _init_db(_DB_PATH)

    # Try the trained XLM-RoBERTa checkpoint first. If anything goes
    # wrong loading it (missing dir, missing weights, torch not
    # installed, etc.) we fall back to the deterministic heuristic
    # scorer so the API stays up. The fallback is *also* passed in as
    # TrainedModelScorer's internal degrade-target so a degraded
    # construction still returns a working ``Scorer``.
    fallback = HeuristicScorer()
    try:
        scorer = TrainedModelScorer(fallback_scorer=fallback)
        if not scorer.using_trained:
            logger.warning(
                "trained model not found — Lusaber API running on %s",
                fallback.model_version,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "trained model failed to load (%s) — falling back to %s",
            exc, fallback.model_version,
        )
        scorer = fallback

    app.state.analyzer = Analyzer(scorer=scorer)

    # Summarizer is cheap to construct (no network, no keys checked
    # eagerly). Actual Anthropic client init happens lazily on the
    # first /summarize request, so the server starts up cleanly even
    # without ANTHROPIC_API_KEY in the environment.
    app.state.summarizer = Summarizer()
    if not app.state.summarizer.available:
        logger.warning(
            "GROQ_API_KEY not set — /summarize will return 503 until configured"
        )

    _STARTED_AT = time.monotonic()
    logger.info("Lusaber API ready · model=%s", app.state.analyzer.scorer.model_version)
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])

app = FastAPI(
    title="Lusaber · Լուսաբեր",
    description="Armenian disinformation detection API. Research prototype.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(_: Request, __: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded — Lusaber accepts 30 req/min/IP"},
    )


@app.middleware("http")
async def _add_powered_by(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["x-powered-by"] = "Lusaber"
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness + model-version probe."""
    return HealthResponse(
        model_version=app.state.analyzer.scorer.model_version,
        uptime_seconds=time.monotonic() - _STARTED_AT,
    )


@app.get("/stats", response_model=StatsResponse, tags=["meta"])
def stats() -> StatsResponse:
    """Aggregate counters since the service started (SQLite-backed)."""
    return StatsResponse(
        model_version=app.state.analyzer.scorer.model_version,
        total_analyses=_get_total_analyses(_DB_PATH),
        uptime_seconds=time.monotonic() - _STARTED_AT,
    )


@app.post("/analyze", response_model=AnalyzeResponse, tags=["analyze"])
@limiter.limit("30/minute")
def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Score one text or URL for credibility.

    At least one of ``text`` or ``url`` must be present. When only ``url``
    is supplied, the API expects an upstream scraper to have fetched the
    body — Lusaber does not fetch arbitrary URLs server-side in v0 to
    keep the SSRF surface minimal.
    """
    if payload.text is None and payload.url is None:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={"detail": "either `text` or `url` is required"},
        )

    result = app.state.analyzer.analyze(
        text=payload.text,
        title=payload.title,
        url=str(payload.url) if payload.url else None,
    )
    _bump_total_analyses(_DB_PATH)

    source_out: SourceAnalysisOut | None = None
    if result.source_analysis is not None:
        source_out = SourceAnalysisOut(**result.source_analysis.as_dict())

    return AnalyzeResponse(
        credibility_score=result.credibility_score,
        verdict=result.verdict,  # type: ignore[arg-type]
        confidence=result.confidence,
        red_flags=result.red_flags,
        source_analysis=source_out,
        processing_time_ms=result.processing_time_ms,
        model_version=result.model_version,
    )


@app.post("/summarize", response_model=SummarizeResponse, tags=["summarize"])
@limiter.limit("10/minute")
def summarize(payload: SummarizeRequest, request: Request) -> SummarizeResponse:
    """Produce bilingual (Armenian + English) summary, entities, topics,
    reading-time, and source-check for a single article.

    Returns 503 when ``ANTHROPIC_API_KEY`` is missing from the server
    environment, 502 if the model returns malformed JSON twice, and
    429 on rate-limit overflow (10 req/min/IP).
    """
    summarizer: Summarizer = app.state.summarizer
    if not summarizer.available:
        return JSONResponse(  # type: ignore[return-value]
            status_code=503,
            content={
                "detail": (
                    "Lusaber summarizer is unavailable — GROQ_API_KEY "
                    "is not set on the server. Set the key and restart."
                )
            },
        )

    try:
        result = summarizer.summarize(
            text=payload.text,
            title=payload.title,
            url=str(payload.url) if payload.url else None,
        )
    except SummarizerUnavailable as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=503, content={"detail": str(exc)}
        )
    except SummarizerFailed as exc:
        logger.warning("summarizer failed: %s", exc)
        return JSONResponse(  # type: ignore[return-value]
            status_code=502,
            content={"detail": f"upstream model returned unparseable output: {exc}"},
        )

    source_out: SourceAnalysisOut | None = None
    if result.source_check is not None:
        source_out = SourceAnalysisOut(**result.source_check.as_dict())

    _bump_total_analyses(_DB_PATH)
    return SummarizeResponse(
        summary_hy=result.summary_hy,
        summary_en=result.summary_en,
        headline_en=result.headline_en,
        entities=EntitiesOut(**result.entities),
        topics=result.topics,
        reading_time_minutes=result.reading_time_minutes,
        language_detected=result.language_detected,  # type: ignore[arg-type]
        source_check=source_out,
        processing_time_ms=result.processing_time_ms,
        model=result.model,
    )
