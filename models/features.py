"""Lusaber · Լուսաբեր — feature extraction (Phase 2).

Provides :class:`FeatureExtractor`, which computes three families of
features per article:

* **Linguistic** — ``emotional_intensity``, ``urgency_score``,
  ``headline_body_consistency``, ``sentence_complexity``,
  ``caps_ratio``, ``exclamation_ratio``.
* **Source** — ``domain_age_days`` (WHOIS), ``has_https``,
  ``domain_in_fake_registry`` (from ``data/fake_domains.json``),
  ``subdomain_mimicry_score`` (Levenshtein vs known outlets),
  ``alexa_rank_proxy`` (small built-in popularity table).
* **Entity** — ``entity_count``, ``verified_entity_ratio``
  (vs ``data/verified_entities.yml``), ``fabricated_quote_flag``
  (heuristic).

Design choices (approved with the user in Phase 2 kickoff)::

    * Lexicons         : hand-curated Armenian word/phrase lists in
                         ``data/lexicons/hy_emotional.txt`` and
                         ``data/lexicons/hy_urgency.txt``.
    * Similarity       : char-level TF-IDF cosine (``analyzer='char_wb'``,
                         ``ngram_range=(3, 5)``) — no extra downloads.
    * Verified entities: ``data/verified_entities.yml`` (~80 entries).
    * Fabricated quote : heuristic — a quote attributed to a verified
                         person where no citation phrase appears nearby.

Optional dependencies are loaded lazily so the class can still be
constructed (with reduced feature coverage) in lightweight test
environments::

    sklearn (required for ``headline_body_consistency``)
    Levenshtein / python-Levenshtein (optional; pure-Python fallback
                                      provided)
    whois (optional; ``domain_age_days`` returns -1 if unavailable)
    spacy + xx_ent_wiki_sm (optional; entity features return zero if
                            unavailable)
    yaml (optional; ``verified_entities`` defaults to empty)
"""

from __future__ import annotations

import dataclasses as dc
import json
import logging
import math
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

logger = logging.getLogger("lusaber.features")

# ---------------------------------------------------------------------------
# Project paths (resolved relative to repo root)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EMOTIONAL_LEXICON = _REPO_ROOT / "data" / "lexicons" / "hy_emotional.txt"
_DEFAULT_URGENCY_LEXICON = _REPO_ROOT / "data" / "lexicons" / "hy_urgency.txt"
_DEFAULT_FAKE_DOMAINS = _REPO_ROOT / "data" / "fake_domains.json"
_DEFAULT_VERIFIED_ENTITIES = _REPO_ROOT / "data" / "verified_entities.yml"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Bare domains we consider authoritative for Levenshtein mimicry detection.
# A scraped article whose domain has high Levenshtein ratio against any of
# these (and is *not* itself one of these) is flagged.
LEGITIMATE_DOMAINS: tuple[str, ...] = (
    "armenpress.am",
    "civilnet.am",
    "media.am",
    "168.am",
    "aravot.am",
    "azatutyun.am",
    "panorama.am",
    "hetq.am",
    "azatutyun.com",
    "cnn.com",
    "reuters.com",
    "bloomberg.com",
    "bbc.com",
    "nytimes.com",
    "rferl.org",
)

# Outlet-name fragments commonly used in mimicry URLs. Detected by
# :meth:`FeatureExtractor._mimicry_brand_match`.
KNOWN_OUTLET_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("cnn", "cnn.com"),
    ("reuters", "reuters.com"),
    ("bloomberg", "bloomberg.com"),
    ("bbc", "bbc.com"),
    ("armenpress", "armenpress.am"),
    ("civilnet", "civilnet.am"),
    ("azatutyun", "azatutyun.am"),
    ("rferl", "rferl.org"),
)

# Rough popularity proxy ("alexa-rank-proxy"): higher = more popular.
# Used as a coarse credibility prior — *not* a ranking. Range [0, 1].
_POPULARITY_PRIOR: dict[str, float] = {
    "armenpress.am": 0.85,
    "civilnet.am": 0.80,
    "media.am": 0.70,
    "azatutyun.am": 0.85,
    "168.am": 0.65,
    "aravot.am": 0.60,
    "panorama.am": 0.65,
    "hetq.am": 0.70,
}

# Armenian quote patterns — the open/close guillemets are standard in
# Armenian typography for direct speech.
_QUOTE_RE = re.compile(r"«([^»]{4,400})»")
# Attribution phrases that, when present near a quote, indicate the quote
# has been sourced (and therefore should not be treated as fabricated).
_CITATION_HINTS_RE = re.compile(
    r"(?:ասաց|հայտնեց|նշեց|գրեց|հայտարարեց|համաձայն|"
    r"փոխանցեց|հաղորդեց|հաղորդագրությամբ|աղբյուր|"
    r"according to|said|told|reported|wrote)",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[.!?։\n]+")

# Hyperparameters
_DEFAULT_TFIDF_NGRAM = (3, 5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_lexicon(path: Path) -> list[str]:
    """Return non-empty, non-comment lines from a lexicon file (lowercased)."""
    if not path.exists():
        logger.warning("lexicon not found: %s", path)
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line.lower())
    return out


def _load_fake_domains(path: Path) -> set[str]:
    """Return a set of bare domain strings from the fake-domains registry."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("failed to parse %s: %s", path, exc)
        return set()
    domains = {d["domain"].lower() for d in data.get("domains", []) if "domain" in d}
    return domains


def _load_verified_entities(path: Path) -> list[str]:
    """Flatten ``verified_entities.yml`` into a list of name surface forms.

    Tolerates a missing PyYAML dependency: falls back to a tiny regex
    parser that just pulls ``names:`` entries.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        logger.info("PyYAML not installed — falling back to regex YAML parsing")
        names: list[str] = []
        for m in re.finditer(r'names:\s*\[(?P<inner>[^\]]+)\]', text):
            for piece in m.group("inner").split(","):
                cleaned = piece.strip().strip('"').strip("'")
                if cleaned:
                    names.append(cleaned)
        return names
    data = yaml.safe_load(text) or {}
    out: list[str] = []
    for section in ("people", "institutions"):
        for entry in data.get(section, []) or []:
            for n in entry.get("names", []):
                if n:
                    out.append(n)
    return out


def _levenshtein_ratio(a: str, b: str) -> float:
    """Return the Levenshtein ratio in [0, 1] between two strings.

    Prefers ``python-Levenshtein`` when available; otherwise falls back
    to a pure-Python DP implementation.
    """
    if not a and not b:
        return 1.0
    try:
        import Levenshtein  # type: ignore[import-not-found]

        return Levenshtein.ratio(a, b)
    except ImportError:
        pass
    # Pure-Python fallback.
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    cur = [0] * (n + 1)
    for i in range(1, m + 1):
        cur[0] = i
        ai = a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev, cur = cur, prev
    dist = prev[n]
    return 1.0 - dist / (m + n) * 2.0  # python-Levenshtein-compatible ratio


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _word_tokens(text: str) -> list[str]:
    """Whitespace tokenize, stripping leading/trailing punctuation per token."""
    return [w.strip(".,;:!?«»\"'()[]{}—–-·։") for w in text.split()]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def _bare_domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# ---------------------------------------------------------------------------
# Feature vector
# ---------------------------------------------------------------------------
@dc.dataclass
class FeatureVector:
    """All numerical signals extracted from a single article.

    Attributes:
        emotional_intensity: Lexicon hits / token count, in [0, 1].
        urgency_score: Urgency-phrase matches / sentence count, in [0, ~).
        headline_body_consistency: Char TF-IDF cosine of title vs first
            paragraph, in [0, 1]. NaN if sklearn is unavailable.
        sentence_complexity: Mean tokens per sentence.
        caps_ratio: ALL-CAPS Latin word ratio (Armenian has no case;
            this captures Western-script shouting embedded in the text).
        exclamation_ratio: ``!``-marks per sentence.
        domain_age_days: WHOIS age in days, ``-1`` if unknown.
        has_https: Boolean → 1.0 / 0.0.
        domain_in_fake_registry: 1.0 if URL's host is in the registry.
        subdomain_mimicry_score: Max Levenshtein ratio against
            ``LEGITIMATE_DOMAINS`` (excluding self-match), in [0, 1].
        alexa_rank_proxy: Hand-tuned popularity prior in [0, 1].
        entity_count: Total spaCy NER spans.
        verified_entity_ratio: Verified hits / entity_count, in [0, 1].
        fabricated_quote_flag: ``1.0`` if any quote attributed to a
            verified speaker lacks a citation hint nearby.
    """

    emotional_intensity: float
    urgency_score: float
    headline_body_consistency: float
    sentence_complexity: float
    caps_ratio: float
    exclamation_ratio: float

    domain_age_days: float
    has_https: float
    domain_in_fake_registry: float
    subdomain_mimicry_score: float
    alexa_rank_proxy: float

    entity_count: float
    verified_entity_ratio: float
    fabricated_quote_flag: float

    def as_dict(self) -> dict[str, float]:
        return dc.asdict(self)

    def as_list(self, order: Iterable[str] | None = None) -> list[float]:
        d = self.as_dict()
        keys = list(order) if order is not None else list(d.keys())
        return [float(d[k]) for k in keys]


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------
class FeatureExtractor:
    """Compute the Lusaber Phase-2 feature vector for a single article.

    Args:
        emotional_lexicon: Path to the Armenian emotional/superlative lexicon.
        urgency_lexicon:   Path to the Armenian urgency lexicon.
        fake_domains:      Path to ``data/fake_domains.json``.
        verified_entities: Path to ``data/verified_entities.yml``.
        nlp:               Optional pre-loaded spaCy ``Language`` object.
            If ``None``, the constructor tries ``xx_ent_wiki_sm``; if
            that is unavailable, entity features are zeroed.
        whois_timeout:     Seconds to wait on a WHOIS query before
            giving up. Default 5.

    The extractor is intentionally cheap to construct so that unit tests
    can instantiate it without network or model downloads.
    """

    def __init__(
        self,
        *,
        emotional_lexicon: Path = _DEFAULT_EMOTIONAL_LEXICON,
        urgency_lexicon: Path = _DEFAULT_URGENCY_LEXICON,
        fake_domains: Path = _DEFAULT_FAKE_DOMAINS,
        verified_entities: Path = _DEFAULT_VERIFIED_ENTITIES,
        nlp: Any | None = None,
        whois_timeout: float = 5.0,
    ) -> None:
        self.emotional_terms: tuple[str, ...] = tuple(_read_lexicon(emotional_lexicon))
        self.urgency_terms: tuple[str, ...] = tuple(_read_lexicon(urgency_lexicon))
        self.fake_domains: set[str] = _load_fake_domains(fake_domains)
        self.verified_entities: tuple[str, ...] = tuple(_load_verified_entities(verified_entities))
        self.whois_timeout = whois_timeout

        # Pre-normalize the verified-entity list for substring matching.
        self._verified_lower: tuple[str, ...] = tuple(e.lower() for e in self.verified_entities)

        # spaCy is optional.
        self.nlp = nlp
        if self.nlp is None:
            try:
                import spacy  # type: ignore[import-not-found]

                self.nlp = spacy.load("xx_ent_wiki_sm")
                logger.info("loaded spaCy xx_ent_wiki_sm")
            except Exception as exc:  # noqa: BLE001
                logger.info("spaCy unavailable — entity features will be 0 (%s)", exc)
                self.nlp = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def extract(self, *, title: str, body_text: str, url: str | None = None) -> FeatureVector:
        """Return the full :class:`FeatureVector` for one article.

        Args:
            title: Article headline.
            body_text: Full article body. May contain newlines.
            url: Optional canonical URL — required for source signals.
                If ``None``, source-signal features default to 0.0 / ``-1``.

        Returns:
            A populated :class:`FeatureVector`.
        """
        # Linguistic ---------------------------------------------------
        norm_body = _normalize(body_text)
        tokens = _word_tokens(body_text)
        sentences = _sentences(body_text)
        n_tokens = max(1, len(tokens))
        n_sent = max(1, len(sentences))

        emotional = self._lexicon_token_hits(tokens, self.emotional_terms) / n_tokens
        urgency = self._lexicon_phrase_hits(norm_body, self.urgency_terms) / n_sent
        consistency = self._headline_body_consistency(title, body_text)
        complexity = sum(len(s.split()) for s in sentences) / n_sent
        caps = self._caps_ratio(tokens)
        excls = body_text.count("!") / n_sent

        # Source -------------------------------------------------------
        if url:
            age = self._domain_age_days(url)
            https = 1.0 if urlparse(url).scheme == "https" else 0.0
            in_fake = 1.0 if _bare_domain(url) in self.fake_domains else 0.0
            mimicry = self._subdomain_mimicry_score(url)
            alexa = _POPULARITY_PRIOR.get(_bare_domain(url), 0.0)
        else:
            age = -1.0
            https = 0.0
            in_fake = 0.0
            mimicry = 0.0
            alexa = 0.0

        # Entities -----------------------------------------------------
        entity_count, verified_ratio, fabricated = self._entity_features(title, body_text)

        return FeatureVector(
            emotional_intensity=float(emotional),
            urgency_score=float(urgency),
            headline_body_consistency=float(consistency),
            sentence_complexity=float(complexity),
            caps_ratio=float(caps),
            exclamation_ratio=float(excls),
            domain_age_days=float(age),
            has_https=float(https),
            domain_in_fake_registry=float(in_fake),
            subdomain_mimicry_score=float(mimicry),
            alexa_rank_proxy=float(alexa),
            entity_count=float(entity_count),
            verified_entity_ratio=float(verified_ratio),
            fabricated_quote_flag=float(fabricated),
        )

    def red_flags(self, fv: FeatureVector, url: str | None = None) -> list[str]:
        """Human-readable explanations for top warning signals.

        Args:
            fv: A computed :class:`FeatureVector`.
            url: Optional URL, used to enrich source flags.

        Returns:
            Plain Armenian / English bilingual strings, ordered by
            severity. Empty list if nothing trips a threshold.
        """
        flags: list[str] = []
        if fv.domain_in_fake_registry:
            flags.append("Domain appears in the known-fake registry.")
        if fv.subdomain_mimicry_score >= 0.75:
            flags.append("Domain closely mimics a legitimate outlet.")
        if 0 <= fv.domain_age_days < 90:
            flags.append(f"Domain is very young (≈{int(fv.domain_age_days)} days).")
        if fv.has_https == 0.0 and url:
            flags.append("Article is served over insecure HTTP.")
        if fv.fabricated_quote_flag:
            flags.append("Quotes attributed to public figures lack source citation.")
        if fv.emotional_intensity > 0.04:
            flags.append("Unusually high density of emotional / loaded language.")
        if fv.urgency_score > 0.4:
            flags.append("Heavy use of urgency / call-to-share phrasing.")
        if fv.caps_ratio > 0.05:
            flags.append("Sustained use of ALL-CAPS in body text.")
        if fv.headline_body_consistency < 0.05:
            flags.append("Headline is poorly aligned with article body.")
        return flags

    # ------------------------------------------------------------------
    # Linguistic helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _lexicon_token_hits(tokens: list[str], terms: tuple[str, ...]) -> int:
        lower = {t.lower() for t in tokens if t}
        return sum(1 for term in terms if term in lower)

    @staticmethod
    def _lexicon_phrase_hits(text: str, terms: tuple[str, ...]) -> int:
        return sum(1 for term in terms if term in text)

    @staticmethod
    def _caps_ratio(tokens: list[str]) -> float:
        if not tokens:
            return 0.0
        latin = [t for t in tokens if t and re.fullmatch(r"[A-Za-z]+", t)]
        if not latin:
            return 0.0
        caps = sum(1 for t in latin if len(t) > 1 and t.isupper())
        return caps / len(latin)

    @staticmethod
    def _headline_body_consistency(title: str, body: str) -> float:
        first_para = body.split("\n\n", 1)[0] if "\n\n" in body else body[:800]
        if not title.strip() or not first_para.strip():
            return 0.0
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            logger.debug("sklearn unavailable; consistency = NaN")
            return float("nan")
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=_DEFAULT_TFIDF_NGRAM)
        try:
            X = vec.fit_transform([title, first_para])
        except ValueError:  # empty vocab on degenerate inputs
            return 0.0
        return float(cosine_similarity(X[0], X[1])[0, 0])

    # ------------------------------------------------------------------
    # Source helpers
    # ------------------------------------------------------------------
    def _domain_age_days(self, url: str) -> float:
        """WHOIS-based domain age in days, ``-1`` if lookup fails.

        Uses ``python-whois`` if installed. Honours :attr:`whois_timeout`
        via ``socket.setdefaulttimeout`` (the library has no native
        timeout knob).
        """
        try:
            import whois  # type: ignore[import-not-found]
        except ImportError:
            logger.debug("python-whois not installed; age=-1")
            return -1.0
        host = _bare_domain(url)
        if not host:
            return -1.0
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(self.whois_timeout)
            data = whois.whois(host)
        except Exception as exc:  # noqa: BLE001
            logger.debug("whois failed for %s: %s", host, exc)
            return -1.0
        finally:
            socket.setdefaulttimeout(old_timeout)
        created = getattr(data, "creation_date", None)
        if isinstance(created, list):
            created = created[0] if created else None
        if not isinstance(created, datetime):
            return -1.0
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).days

    def _subdomain_mimicry_score(self, url: str) -> float:
        """Max Levenshtein ratio of the host against the legitimate-domain
        list. Returns 0.0 if the host is itself a legitimate outlet
        (its near-twin sibling in the list is not a mimic), otherwise
        the highest ratio found. High values indicate a typosquat."""
        host = _bare_domain(url)
        if not host or host in LEGITIMATE_DOMAINS:
            return 0.0
        best = 0.0
        for legit in LEGITIMATE_DOMAINS:
            r = _levenshtein_ratio(host, legit)
            if r > best:
                best = r
        return best

    @staticmethod
    def _mimicry_brand_match(url: str) -> str | None:
        """Return a known outlet name that appears as a URL fragment but
        whose canonical domain does not match. Returns ``None`` if no
        suspicious mimicry pattern is found."""
        host = _bare_domain(url)
        url_lower = url.lower()
        for frag, canonical in KNOWN_OUTLET_FRAGMENTS:
            if frag in url_lower and host != canonical:
                return canonical
        return None

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------
    def _entity_features(self, title: str, body: str) -> tuple[int, float, float]:
        """Return ``(entity_count, verified_ratio, fabricated_flag)``.

        If spaCy isn't available, ``entity_count`` falls back to a
        coarse heuristic (count of verified-entity surface-form matches)
        and ``verified_ratio`` becomes 1.0 iff any hits were found.
        """
        combined = f"{title}\n\n{body}"
        ents: list[str] = []
        if self.nlp is not None:
            try:
                doc = self.nlp(combined[:8000])  # bound work
                ents = [e.text for e in doc.ents if e.text.strip()]
            except Exception as exc:  # noqa: BLE001
                logger.debug("spaCy failure on this doc: %s", exc)

        if ents:
            verified_hits = sum(
                1 for e in ents if any(v in e.lower() for v in self._verified_lower)
            )
            ratio = verified_hits / max(1, len(ents))
        else:
            verified_hits = sum(
                1 for v in self._verified_lower if v and v in combined.lower()
            )
            ratio = 1.0 if verified_hits > 0 else 0.0

        fabricated = self._fabricated_quote_flag(body)
        return (len(ents) or verified_hits, ratio, fabricated)

    def _fabricated_quote_flag(self, body: str) -> float:
        """Heuristic: 1.0 if any «...» quote is attributed to a verified
        public figure but no citation hint appears within ±200 chars."""
        for m in _QUOTE_RE.finditer(body):
            start, end = m.span()
            ctx = body[max(0, start - 200): min(len(body), end + 200)]
            ctx_lower = ctx.lower()
            speaker = next(
                (v for v in self._verified_lower if v and len(v) > 3 and v in ctx_lower),
                None,
            )
            if speaker is None:
                continue
            if _CITATION_HINTS_RE.search(ctx):
                continue
            return 1.0
        return 0.0


# ---------------------------------------------------------------------------
# Convenience: feature ordering used by downstream models
# ---------------------------------------------------------------------------
FEATURE_ORDER: tuple[str, ...] = (
    "emotional_intensity",
    "urgency_score",
    "headline_body_consistency",
    "sentence_complexity",
    "caps_ratio",
    "exclamation_ratio",
    "domain_age_days",
    "has_https",
    "domain_in_fake_registry",
    "subdomain_mimicry_score",
    "alexa_rank_proxy",
    "entity_count",
    "verified_entity_ratio",
    "fabricated_quote_flag",
)


# ---------------------------------------------------------------------------
# Phase 4 — source fingerprinting
# ---------------------------------------------------------------------------
@dc.dataclass
class SourceAnalysis:
    """Structured outcome of :meth:`SourceAnalyzer.analyze`.

    Attributes:
        domain: Bare host of the analyzed URL.
        in_fake_registry: True if ``domain`` is in ``fake_domains.json``.
        is_legitimate_outlet: True if ``domain`` is in
            :data:`LEGITIMATE_DOMAINS` (Lusaber's whitelist).
        matched_domain: Closest legitimate outlet for the mimicry probe.
            ``None`` if no host or if the host is itself a legitimate outlet.
        similarity_score: Levenshtein ratio against ``matched_domain``, in
            [0, 1]. 0.0 when no probe is run.
        brand_fragment_match: Real outlet name whose fragment appears in
            the URL but whose canonical domain does not match. ``None``
            if no mimicry-by-fragment pattern is found.
        verdict: ``"legitimate"``, ``"known-fake"``, ``"likely-mimicry"``,
            or ``"unknown"``.
        explanation: One-line human-readable summary of the verdict.
    """

    domain: str
    in_fake_registry: bool
    is_legitimate_outlet: bool
    matched_domain: str | None
    similarity_score: float
    brand_fragment_match: str | None
    verdict: str
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


class SourceAnalyzer:
    """Domain-level disinformation signals for a single URL.

    Combines three checks per the Phase-4 spec:

    1. Fake-domain registry lookup (``data/fake_domains.json``).
    2. Levenshtein-similarity scan against the legitimate-outlets list;
       similarity > ``mimicry_threshold`` (default 0.75) is flagged.
    3. Brand-fragment mimicry: URL contains a known outlet name (``cnn``,
       ``reuters``, ``bloomberg``, ``armenpress``, etc.) but the
       canonical domain does not match.

    Args:
        fake_domains: Path to the registry JSON. Defaults to
            ``data/fake_domains.json`` at repo root.
        mimicry_threshold: Levenshtein-ratio cutoff above which a
            non-self match counts as a typosquat. Default ``0.75``.
    """

    def __init__(
        self,
        *,
        fake_domains: Path = _DEFAULT_FAKE_DOMAINS,
        mimicry_threshold: float = 0.75,
    ) -> None:
        self.fake_domains: set[str] = _load_fake_domains(fake_domains)
        self.mimicry_threshold = mimicry_threshold

    def analyze(self, url: str) -> SourceAnalysis:
        """Return a :class:`SourceAnalysis` for ``url``.

        Args:
            url: Absolute URL of the article under inspection.

        Returns:
            A populated :class:`SourceAnalysis`.
        """
        host = _bare_domain(url)
        is_legit = host in LEGITIMATE_DOMAINS
        in_fake = host in self.fake_domains

        # Levenshtein probe (skipped for legitimate siblings).
        matched: str | None = None
        score = 0.0
        if host and not is_legit:
            for legit in LEGITIMATE_DOMAINS:
                r = _levenshtein_ratio(host, legit)
                if r > score:
                    score, matched = r, legit

        brand = (
            FeatureExtractor._mimicry_brand_match(url) if not is_legit else None
        )

        # Verdict precedence (most specific first):
        #   known-fake  >  legitimate  >  brand-fragment  >  mimicry-score  >  unknown
        # Brand-fragment is preferred over Levenshtein because it yields a
        # clearer explanation when both fire on the same URL (e.g.
        # "armenian-reuters-breaking.net").
        if in_fake:
            verdict = "known-fake"
            explanation = f"{host} is in the known-fake registry."
        elif is_legit:
            verdict = "legitimate"
            explanation = f"{host} is in Lusaber's verified-outlet whitelist."
        elif brand is not None:
            verdict = "likely-mimicry"
            explanation = (
                f"URL contains the '{brand.split('.')[0]}' fragment but the "
                f"domain ({host}) does not match {brand}."
            )
        elif score >= self.mimicry_threshold and matched is not None:
            verdict = "likely-mimicry"
            explanation = (
                f"{host} is {score:.0%} similar to legitimate outlet {matched}."
            )
        else:
            verdict = "unknown"
            explanation = f"No matching registry entry or mimicry pattern for {host}."

        return SourceAnalysis(
            domain=host,
            in_fake_registry=in_fake,
            is_legitimate_outlet=is_legit,
            matched_domain=matched if not is_legit else None,
            similarity_score=score if not is_legit else 0.0,
            brand_fragment_match=brand,
            verdict=verdict,
            explanation=explanation,
        )


__all__ = [
    "FeatureExtractor",
    "FeatureVector",
    "FEATURE_ORDER",
    "LEGITIMATE_DOMAINS",
    "KNOWN_OUTLET_FRAGMENTS",
    "SourceAnalyzer",
    "SourceAnalysis",
]
