"""Lusaber · Լուսաբեր — Armenian news summarizer.

Wraps the Groq API (free tier) to produce a structured summary of an
Armenian-language news article in both Armenian and English, plus
extracted entities, topic tags, language detection, and a reading-time
estimate. The :class:`SourceAnalyzer` from Phase 4 is reused so every
summary also carries the same domain-fingerprinting signals the
``/analyze`` endpoint exposes.

The client is constructed lazily on first use — if ``GROQ_API_KEY``
is unset, the API layer returns HTTP 503 instead of crashing at
startup.

Wire-format contract (matches :class:`api.schemas.SummarizeResponse`)::

    {
      "summary_hy": "...",
      "summary_en": "...",
      "headline_en": "...",
      "entities": {
        "people":        [...],
        "places":        [...],
        "organizations": [...]
      },
      "topics": [...],
      "reading_time_minutes": float,
      "language_detected": "hy" | "ru" | "en" | "mixed",
      "source_check": SourceAnalysis | None,
      "processing_time_ms": float,
      "model": "llama-3.3-70b-versatile"
    }
"""

from __future__ import annotations

import dataclasses as dc
import json
import logging
import os
import re
import time
from typing import Any

from models.features import SourceAnalysis, SourceAnalyzer

logger = logging.getLogger("lusaber.summarizer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_OUTPUT_TOKENS = 2048
WORDS_PER_MINUTE = 200  # used for reading-time estimate

# Unicode script ranges relevant to Armenian news.
_ARM_RE = re.compile(r"[԰-֏ﬓ-ﬗ]")  # Armenian block + ligatures
_CYR_RE = re.compile(r"[Ѐ-ӿ]")               # Cyrillic block
_LAT_RE = re.compile(r"[A-Za-z]")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dc.dataclass
class SummaryResult:
    """Structured output of :meth:`Summarizer.summarize`."""

    summary_hy: str
    summary_en: str
    headline_en: str
    entities: dict[str, list[str]]
    topics: list[str]
    reading_time_minutes: float
    language_detected: str
    source_check: SourceAnalysis | None
    processing_time_ms: float
    model: str


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class SummarizerUnavailable(RuntimeError):
    """Raised when ``GROQ_API_KEY`` is absent. The API layer
    translates this to HTTP 503."""


class SummarizerFailed(RuntimeError):
    """Raised when the Groq call (incl. one retry) returns
    unparseable JSON or non-text content."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "You are an expert Armenian-English bilingual journalist working as a "
    "newsroom desk editor. You read Armenian-language news (the article "
    "may also be in Russian or contain English fragments) and produce a "
    "compact, faithful, neutral summary that another journalist can "
    "skim in under a minute.\n\n"
    "Hard rules:\n"
    "  • Never invent facts, quotes, or attributions. If a detail is "
    "absent in the source, omit it — do NOT speculate or paraphrase "
    "into something the article does not say.\n"
    "  • Preserve named entities exactly as they appear (Armenian "
    "spelling for Armenian names; standard transliteration for the "
    "English summary).\n"
    "  • Stay neutral. Don't editorialise, moralise, or label the source "
    "as propaganda or disinformation — that is a separate Lusaber "
    "subsystem.\n"
    "  • Always return a single valid JSON object as your entire "
    "response. No surrounding prose, no Markdown code fences."
)

_USER_PROMPT_TEMPLATE = """Analyze the following Armenian news article and return a single JSON object with EXACTLY these keys (no others):

  summary_hy        — 2–4 sentence summary in fluent Armenian (Հայերեն), faithful to the article. Use ՛ ՚ ՜ guillemets as in the original.
  summary_en        — 2–4 sentence summary in clear English, factually equivalent to summary_hy.
  headline_en       — A single English headline (≤ 90 chars), AP/Reuters style, no clickbait, no question marks.
  entities          — Object with three lists, each ≤ 6 items, deduped:
                        people:        proper-noun people mentioned in the article
                        places:        cities, regions, countries, geographic features
                        organizations: parties, ministries, companies, NGOs, agencies
  topics            — 2–5 topic tags from this fixed vocabulary (use only these strings, case-sensitive):
                      ["politics","economy","society","foreign-policy","security","defence",
                       "judiciary","elections","media","culture","sports","health","tech",
                       "diaspora","environment","breaking"]
  language_detected — One of: "hy" (Armenian), "ru" (Russian), "en" (English), or "mixed".

Title (may be empty): {title}
URL (may be empty): {url}

Article body:
\"\"\"
{body}
\"\"\"

Return ONLY the JSON object — no commentary, no Markdown."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _detect_language(text: str) -> str:
    """Cheap script-based language heuristic.

    Returns ``"hy" | "ru" | "en" | "mixed"`` based on which Unicode
    block dominates the character count. ``"mixed"`` when the leading
    block holds less than 60% of letter chars.
    """
    if not text:
        return "hy"
    arm = len(_ARM_RE.findall(text))
    cyr = len(_CYR_RE.findall(text))
    lat = len(_LAT_RE.findall(text))
    total = arm + cyr + lat
    if total == 0:
        return "hy"
    parts = {"hy": arm, "ru": cyr, "en": lat}
    winner = max(parts, key=parts.get)  # type: ignore[arg-type]
    if parts[winner] / total < 0.6:
        return "mixed"
    return winner


def _reading_time_minutes(text: str) -> float:
    if not text:
        return 0.0
    words = max(1, len(text.split()))
    return round(words / WORDS_PER_MINUTE, 1)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _coerce_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from a model response.

    Tries (in order) raw parse, fenced ``json`` block, and finally the
    first balanced ``{...}`` span. Raises ``json.JSONDecodeError`` if
    nothing parses.
    """
    text = text.strip()
    # 1. raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. ```json ... ``` fence
    m = _JSON_FENCE_RE.search(text)
    if m:
        return json.loads(m.group(1))
    # 3. first-to-last brace
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no JSON object found", text, 0)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------
class Summarizer:
    """Stateful wrapper that lazily instantiates a Groq client.

    Args:
        model: Groq model identifier. Defaults to
            ``llama-3.3-70b-versatile``.
        source_analyzer: Optional pre-built :class:`SourceAnalyzer`.
            Created on demand if omitted.
        client_factory: Optional callable returning a Groq client
            (or any object exposing ``chat.completions.create``).
            Tests inject a mock here to avoid network calls.
        max_output_tokens: Cap on the model's response length.
        temperature: Sampling temperature. 0.3 keeps the summarizer
            faithful while still allowing fluent English/Armenian
            rewriting.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        source_analyzer: SourceAnalyzer | None = None,
        client_factory=None,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        temperature: float = 0.3,
    ) -> None:
        self.model = model
        self.source_analyzer = source_analyzer or SourceAnalyzer()
        self._client_factory = client_factory
        self._client: Any | None = None
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """``True`` if an API key is in the environment or a factory
        has been injected. Cheap — does not actually construct the
        client."""
        return bool(os.environ.get("GROQ_API_KEY")) or self._client_factory is not None

    # ------------------------------------------------------------------
    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client
        if not os.environ.get("GROQ_API_KEY"):
            raise SummarizerUnavailable(
                "GROQ_API_KEY is not set — set it in the environment and "
                "restart the Lusaber API to enable /summarize."
            )
        from groq import Groq  # local import keeps cold start light

        self._client = Groq(api_key=os.environ["GROQ_API_KEY"])
        return self._client

    # ------------------------------------------------------------------
    def _invoke(self, *, title: str, url: str, body: str) -> str:
        """Single Groq call. Returns the model's raw text content.

        Groq exposes an OpenAI-compatible ``chat.completions.create``
        endpoint and supports server-side JSON mode via
        ``response_format={"type": "json_object"}``, which we use to
        eliminate the markdown-fence noise we'd otherwise have to peel
        off in :func:`_coerce_json`.
        """
        client = self._ensure_client()
        user_msg = _USER_PROMPT_TEMPLATE.format(
            title=title or "", url=url or "", body=body
        )
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=self._max_output_tokens,
            temperature=self._temperature,
            response_format={"type": "json_object"},
        )
        # OpenAI-style: choices[0].message.content
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return ""
        msg = getattr(choices[0], "message", None)
        content = getattr(msg, "content", None) if msg is not None else None
        return (content or "").strip()

    # ------------------------------------------------------------------
    def summarize(
        self,
        *,
        text: str,
        title: str | None = None,
        url: str | None = None,
    ) -> SummaryResult:
        """Produce a :class:`SummaryResult` for one article.

        Args:
            text: Article body in Armenian (Russian / English fragments allowed).
            title: Optional headline supplied by the caller.
            url: Optional canonical URL — drives the source-check field.

        Raises:
            ValueError: if ``text`` is empty.
            SummarizerUnavailable: if no API key and no test factory.
            SummarizerFailed: if the model returns unparseable JSON
                even after one retry.
        """
        if not text or not text.strip():
            raise ValueError("text must be non-empty")

        started = time.perf_counter()
        body = text.strip()
        title_clean = (title or "").strip()
        url_clean = (url or "").strip()

        raw = self._invoke(title=title_clean, url=url_clean, body=body)
        try:
            data = _coerce_json(raw)
        except json.JSONDecodeError as exc:
            logger.warning("summarizer JSON parse failed; retrying once (%s)", exc)
            raw = self._invoke(title=title_clean, url=url_clean, body=body)
            try:
                data = _coerce_json(raw)
            except json.JSONDecodeError as exc2:
                raise SummarizerFailed(
                    f"Anthropic returned unparseable JSON twice: {exc2}"
                ) from exc2

        ents = data.get("entities") or {}
        if not isinstance(ents, dict):
            ents = {}
        norm_entities = {
            "people":        [str(x) for x in (ents.get("people") or [])][:6],
            "places":        [str(x) for x in (ents.get("places") or [])][:6],
            "organizations": [str(x) for x in (ents.get("organizations") or [])][:6],
        }
        topics = [str(t) for t in (data.get("topics") or [])][:5]

        source_check = self.source_analyzer.analyze(url_clean) if url_clean else None

        # Prefer the model's language verdict; fall back to script heuristic.
        lang = str(data.get("language_detected") or _detect_language(body)).lower()
        if lang not in {"hy", "ru", "en", "mixed"}:
            lang = _detect_language(body)

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        return SummaryResult(
            summary_hy=str(data.get("summary_hy") or "").strip(),
            summary_en=str(data.get("summary_en") or "").strip(),
            headline_en=str(data.get("headline_en") or "").strip(),
            entities=norm_entities,
            topics=topics,
            reading_time_minutes=_reading_time_minutes(body),
            language_detected=lang,
            source_check=source_check,
            processing_time_ms=round(elapsed_ms, 2),
            model=self.model,
        )
