"""Lusaber · Լուսաբեր — analyzer service layer.

Wraps :class:`models.features.FeatureExtractor` and
:class:`models.features.SourceAnalyzer` behind an :class:`Analyzer`
class that the FastAPI endpoints call.

Until Phase 3 lands a trained calibrated ensemble, scoring is provided
by :class:`HeuristicScorer`, a deterministic feature-weighted scorer
that mimics the calibrated model's output shape so the API contract
remains stable. The model_version string reports
``"lusaber-heuristic-v0"`` until the real model replaces it.
"""

from __future__ import annotations

import dataclasses as dc
import logging
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from models.features import (
    FEATURE_ORDER,
    FeatureExtractor,
    FeatureVector,
    SourceAnalysis,
    SourceAnalyzer,
)

logger = logging.getLogger("lusaber.analyzer")

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dc.dataclass
class AnalysisResult:
    """Output of :meth:`Analyzer.analyze` before serialization."""

    credibility_score: float
    verdict: str
    confidence: float
    red_flags: list[str]
    source_analysis: SourceAnalysis | None
    processing_time_ms: float
    model_version: str


# ---------------------------------------------------------------------------
# Scoring strategy
# ---------------------------------------------------------------------------
class Scorer(Protocol):
    """Protocol implemented by every scoring backend.

    A scorer takes a feature vector + optional source analysis +
    optional raw text and returns ``(credibility_score, confidence,
    model_version)``.

    ``title`` / ``body_text`` are only used by text-based scorers
    (e.g. :class:`TrainedModelScorer`); feature-based scorers like
    :class:`HeuristicScorer` accept them for signature parity and
    ignore them.
    """

    def score(
        self,
        fv: FeatureVector,
        source: SourceAnalysis | None,
        *,
        title: str = "",
        body_text: str = "",
    ) -> tuple[float, float, str]: ...

    @property
    def model_version(self) -> str: ...


class HeuristicScorer:
    """Deterministic feature-weighted scorer used until the trained
    ensemble (Phase 3) is available.

    The score is anchored at 65 (neutral) and adjusted by:

    * Source verdict (large, decisive shifts).
    * Style features (emotional, urgency, caps, exclamations).
    * Heuristic flags (fabricated quote, low headline-body cosine).

    Confidence is bounded in [0.4, 0.9] — it is intentionally conservative
    so frontends know not to over-trust pre-training output.
    """

    model_version = "lusaber-heuristic-v0"

    def score(
        self,
        fv: FeatureVector,
        source: SourceAnalysis | None,
        *,
        title: str = "",
        body_text: str = "",
    ) -> tuple[float, float, str]:
        # title / body_text accepted for Scorer-protocol parity; the
        # heuristic scorer reads everything it needs off ``fv``.
        del title, body_text
        s = 65.0  # neutral anchor

        # Source signal — large, decisive shifts.
        if source is not None:
            if source.verdict == "known-fake":
                s -= 55.0
            elif source.verdict == "likely-mimicry":
                s -= 30.0
            elif source.verdict == "legitimate":
                s += 15.0

        # Style signals — modest, additive.
        s -= min(30.0, fv.emotional_intensity * 600.0)
        s -= min(20.0, fv.urgency_score * 30.0)
        s -= min(15.0, fv.caps_ratio * 200.0)
        s -= min(10.0, fv.exclamation_ratio * 40.0)

        # Heuristic flags.
        if fv.fabricated_quote_flag and (source is None or not source.is_legitimate_outlet):
            s -= 15.0
        if fv.headline_body_consistency < 0.05:
            s -= 5.0

        # Positive lift: a high verified-entity ratio is the only path
        # above the 65 boundary when no source signal is available. Clean
        # style alone is just "no negative signals" and is intentionally
        # not lifted — otherwise generic neutral text from unknown
        # domains would slip into LIKELY CREDIBLE without any real
        # positive evidence.
        if fv.verified_entity_ratio >= 0.5:
            s += 10.0

        # Clamp into [2, 98] rather than [0, 100]: an exact 0/100 reads as a
        # bug in a live demo and forecloses any human override. The bounded
        # band still expresses "nearly certain" without a hard rail.
        s = max(2.0, min(98.0, s))
        # Confidence inflates when source signal is strong, deflates when
        # we have only style cues to go on.
        if source is not None and source.verdict in ("known-fake", "legitimate"):
            confidence = 0.85
        elif source is not None and source.verdict == "likely-mimicry":
            confidence = 0.75
        else:
            confidence = 0.5
        return s, confidence, self.model_version


# ---------------------------------------------------------------------------
# Trained XLM-RoBERTa scorer (Phase 3 output)
# ---------------------------------------------------------------------------
_DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parent.parent
    / "models" / "checkpoints" / "xlmr-lusaber-best"
)


class TrainedModelScorer:
    """Soft-vote-free Phase-3 scorer driven by the fine-tuned XLM-RoBERTa.

    On construction the model + tokenizer are loaded into RAM and the
    module is switched to ``eval`` mode. Each ``score()`` call runs a
    single forward pass under ``torch.no_grad()``.

    Args:
        model_dir: Path to a HuggingFace ``save_pretrained`` directory.
            Defaults to ``models/checkpoints/xlmr-lusaber-best`` at the
            repo root.
        fallback_scorer: Used when the model can't be loaded (missing
            files, malformed config, etc.). If ``None`` and loading
            fails, the constructor raises ``FileNotFoundError``.
        max_length: Tokenizer truncation length.
        body_chars: Characters of body text used at inference. Matches
            the training input format.

    Score mapping per the user's spec:

    * ``credibility_score = 100 × P(label = credible)``
    * ``confidence = max(p_disinfo, p_credible)`` clamped to
      ``[0.4, 0.95]`` — the floor prevents over-claiming on a
      barely-confident model, the ceiling reserves "absolutely certain"
      as a band the heuristic cannot occupy.

    ``model_version`` returns ``"lusaber-xlmr-v1"`` when the trained
    model loaded successfully, or the fallback's ``model_version``
    otherwise.
    """

    def __init__(
        self,
        model_dir: Path | str = _DEFAULT_MODEL_DIR,
        *,
        fallback_scorer: "Scorer | None" = None,
        max_length: int = 512,
        body_chars: int = 1000,
    ) -> None:
        self.model_dir = Path(model_dir)
        self._max_length = max_length
        self._body_chars = body_chars
        self._fallback = fallback_scorer
        self._model = None
        self._tokenizer = None
        self._torch = None

        try:
            self._load_model()
        except (FileNotFoundError, OSError, ImportError, ValueError) as exc:
            if self._fallback is None:
                raise FileNotFoundError(
                    f"trained model not loadable at {self.model_dir} ({exc}); "
                    "supply a fallback_scorer to degrade gracefully"
                ) from exc
            logger.warning(
                "TrainedModelScorer falling back to %s — model not loadable at %s: %s",
                type(self._fallback).__name__, self.model_dir, exc,
            )

    # ------------------------------------------------------------------
    @property
    def model_version(self) -> str:
        if self._model is not None:
            return "lusaber-xlmr-v1"
        assert self._fallback is not None  # __init__ guarantees this
        return self._fallback.model_version

    @property
    def using_trained(self) -> bool:
        """``True`` if the transformer is loaded; ``False`` if running fallback."""
        return self._model is not None

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """Load tokenizer + classifier. Raises if the directory is unusable."""
        if not self.model_dir.exists():
            raise FileNotFoundError(self.model_dir)
        required = ("config.json",)
        for name in required:
            if not (self.model_dir / name).exists():
                raise FileNotFoundError(self.model_dir / name)
        # safetensors or pytorch_model.bin is acceptable — HF picks
        weights_ok = (
            (self.model_dir / "model.safetensors").exists()
            or (self.model_dir / "pytorch_model.bin").exists()
        )
        if not weights_ok:
            raise FileNotFoundError(self.model_dir / "model.safetensors")

        # Imports are deferred so an HF-less environment can still
        # construct HeuristicScorer-only Analyzers.
        import torch  # type: ignore[import-not-found]
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        model = AutoModelForSequenceClassification.from_pretrained(str(self.model_dir))
        model.eval()
        self._model = model
        logger.info("TrainedModelScorer loaded XLM-RoBERTa from %s", self.model_dir)

    # ------------------------------------------------------------------
    @staticmethod
    def _format_input(title: str, body: str, body_chars: int) -> str:
        """Same format used in training: ``title + ' [SEP] ' + body[:N]``."""
        title = (title or "").strip()
        body = (body or "").strip()[:body_chars]
        return f"{title} [SEP] {body}" if title else body

    # ------------------------------------------------------------------
    def score(
        self,
        fv: FeatureVector,
        source: SourceAnalysis | None,
        *,
        title: str = "",
        body_text: str = "",
    ) -> tuple[float, float, str]:
        # Degraded path — model wasn't loadable; delegate.
        if self._model is None:
            assert self._fallback is not None
            return self._fallback.score(fv, source, title=title, body_text=body_text)

        # Empty input safety: trying to run the transformer on "" is
        # technically valid (tokenizer adds <s></s>) but the resulting
        # probability is uninformative. Treat as truly uncertain.
        if not (title or body_text).strip():
            return 50.0, 0.4, self.model_version

        assert self._torch is not None and self._tokenizer is not None
        text = self._format_input(title, body_text, self._body_chars)
        enc = self._tokenizer(
            text,
            max_length=self._max_length,
            truncation=True,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            out = self._model(**enc)
        probs = self._torch.softmax(out.logits, dim=-1).squeeze(0).tolist()
        # Class layout matches training: 0 = disinformation, 1 = credible.
        p_disinfo, p_credible = float(probs[0]), float(probs[1])

        score = 100.0 * p_credible
        confidence = min(0.95, max(0.4, max(p_disinfo, p_credible)))
        return score, confidence, self.model_version


# ---------------------------------------------------------------------------
# Verdict mapping (matches Phase 3c thresholds)
# ---------------------------------------------------------------------------
def _verdict_from_score(score: float) -> str:
    if score < 40.0:
        return "LIKELY DISINFORMATION"
    if score > 65.0:
        return "LIKELY CREDIBLE"
    return "UNCERTAIN"


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------
class Analyzer:
    """Top-level service object the FastAPI handlers call into.

    Args:
        extractor: Optional pre-built :class:`FeatureExtractor`. If
            omitted, a default one is constructed (no spaCy if model
            isn't installed; graceful degradation).
        source_analyzer: Optional pre-built :class:`SourceAnalyzer`.
        scorer: Pluggable scoring strategy. Defaults to
            :class:`HeuristicScorer`. Will be replaced by the calibrated
            Phase-3 ensemble once weights are available.
    """

    def __init__(
        self,
        *,
        extractor: FeatureExtractor | None = None,
        source_analyzer: SourceAnalyzer | None = None,
        scorer: Scorer | None = None,
    ) -> None:
        self.extractor = extractor or FeatureExtractor()
        self.source_analyzer = source_analyzer or SourceAnalyzer()
        self.scorer: Scorer = scorer or HeuristicScorer()

    def analyze(
        self,
        *,
        text: str | None,
        title: str | None,
        url: str | None,
    ) -> AnalysisResult:
        """Score a single document.

        Args:
            text: Article body. Must be provided unless ``url`` is given
                (in which case the caller is responsible for fetching).
            title: Headline. Optional.
            url: Article URL. Optional, but enables source signals.

        Returns:
            An :class:`AnalysisResult`.

        Raises:
            ValueError: if both ``text`` and ``url`` are ``None``.
        """
        if text is None and url is None:
            raise ValueError("at least one of `text` or `url` must be provided")

        started = time.perf_counter()

        body = text or ""
        head = title or self._title_from_body(body)
        fv = self.extractor.extract(title=head, body_text=body, url=url)
        source = self.source_analyzer.analyze(url) if url else None

        score, confidence, model_version = self.scorer.score(
            fv, source, title=head, body_text=body,
        )

        # Source-based safety rails applied uniformly across scorers.
        # The trained transformer reads only the article text and has
        # no way to learn domain provenance; the heuristic scorer
        # already encodes these as soft signals. Applying them here
        # lets both scorers honour the source verdict as a hard
        # constraint. Legitimate sources get *both* a floor of 75 and
        # a small +5 bonus — without the bonus, a model output already
        # above the floor (a common case on neutral text) would never
        # be lifted, and the same text on a legitimate vs. unknown
        # outlet would receive the same score.
        if source is not None:
            if source.verdict == "known-fake":
                score = min(score, 5.0)
            elif source.verdict == "likely-mimicry":
                score = min(score, 30.0)
            elif source.verdict == "legitimate":
                score = min(98.0, max(75.0, score + 5.0))

        verdict = _verdict_from_score(score)

        red_flags = self.extractor.red_flags(fv, url=url)
        if source is not None:
            if source.verdict == "known-fake":
                red_flags.insert(0, source.explanation)
            elif source.verdict == "likely-mimicry":
                red_flags.insert(0, source.explanation)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return AnalysisResult(
            credibility_score=round(score, 2),
            verdict=verdict,
            confidence=round(confidence, 3),
            red_flags=red_flags,
            source_analysis=source,
            processing_time_ms=round(elapsed_ms, 2),
            model_version=model_version,
        )

    @staticmethod
    def _title_from_body(body: str) -> str:
        """Best-effort headline guess when no title is supplied."""
        if not body:
            return ""
        first_line = body.split("\n", 1)[0].strip()
        return first_line[:200]
