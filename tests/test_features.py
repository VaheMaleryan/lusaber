"""Lusaber · Լուսաբեր — unit tests for :class:`models.features.FeatureExtractor`.

Tests are deterministic and avoid any network or model-download
dependencies. WHOIS, sklearn, and spaCy are exercised only when locally
installed; otherwise the relevant assertions degrade to "feature is
finite and within type bounds".
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from models.features import (
    FEATURE_ORDER,
    FeatureExtractor,
    FeatureVector,
    _levenshtein_ratio,  # type: ignore[attr-defined]  # exercised in tests
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
CREDIBLE_TITLE = "Միրզոյանը հանդիպեց Եվրամիության պատվիրակության հետ"
CREDIBLE_BODY = (
    "Հայաստանի արտգործնախարար Արարատ Միրզոյանն այսօր հանդիպեց "
    "Եվրամիության պատվիրակության հետ Երևանում: Կողմերը քննարկեցին "
    "տնտեսական համագործակցության հարցեր, ինչպես հայտնեց արտգործնախարարությունը:"
    "\n\nՀանդիպման ընթացքում Միրզոյանը նշեց, որ Հայաստանը շարունակում է "
    "բարեփոխումների ճանապարհին և համոզված է, որ համագործակցությունը կամրապնդվի, "
    "հաղորդեց Armenpress լրատվական գործակալությունը:"
)

DISINFO_TITLE = "ՇՏԱՊ! Փաշինյանը գաղտնի գործարք է կնքել"
DISINFO_BODY = (
    "ՇՏԱՊ տարածեք!!! Փաշինյանն այսօր ստորագրեց ԴԱՎԱՃԱՆԱԿԱՆ ու սարսափելի "
    "գործարք: «Մենք ստրուկ ենք դարձել», - ասում է վարչապետը՝ խոստովանելով "
    "ողբերգական ճշմարտությունը: Հենց հիմա պետք է գործել, մինչ ուշ չէ! "
    "Փրկեք երկիրը! Տարածեք, մինչ դեռ ուշ չէ!!! ԲԱՑԱՀԱՅՏԵՔ դավադրությունը!"
)


@pytest.fixture(scope="module")
def fx() -> FeatureExtractor:
    # Force-disable spaCy by passing nlp=False sentinel via plain None
    # and rely on graceful degradation when xx_ent_wiki_sm isn't installed.
    return FeatureExtractor(nlp=None, whois_timeout=1.0)


# ---------------------------------------------------------------------------
# Shape & contract
# ---------------------------------------------------------------------------
def test_feature_vector_has_all_fields(fx: FeatureExtractor) -> None:
    fv = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY, url=None)
    assert isinstance(fv, FeatureVector)
    d = fv.as_dict()
    assert set(d.keys()) == set(FEATURE_ORDER)


def test_feature_vector_serialisable_as_list(fx: FeatureExtractor) -> None:
    fv = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    vec = fv.as_list(order=FEATURE_ORDER)
    assert len(vec) == len(FEATURE_ORDER)
    assert all(isinstance(x, float) for x in vec)


def test_lexicons_loaded(fx: FeatureExtractor) -> None:
    # Hand-curated lexicons should be non-trivial in size.
    assert len(fx.emotional_terms) > 50, "emotional lexicon looks empty"
    assert len(fx.urgency_terms) > 50, "urgency lexicon looks empty"


def test_verified_entities_loaded(fx: FeatureExtractor) -> None:
    assert any("Միրզոյան" in n for n in fx.verified_entities)
    assert any("Pashinyan" in n for n in fx.verified_entities)


# ---------------------------------------------------------------------------
# Linguistic signals
# ---------------------------------------------------------------------------
def test_disinfo_has_more_emotional_intensity(fx: FeatureExtractor) -> None:
    cred = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    dis = fx.extract(title=DISINFO_TITLE, body_text=DISINFO_BODY)
    assert dis.emotional_intensity > cred.emotional_intensity


def test_disinfo_has_more_urgency(fx: FeatureExtractor) -> None:
    cred = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    dis = fx.extract(title=DISINFO_TITLE, body_text=DISINFO_BODY)
    assert dis.urgency_score > cred.urgency_score


def test_disinfo_has_more_exclamations(fx: FeatureExtractor) -> None:
    cred = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    dis = fx.extract(title=DISINFO_TITLE, body_text=DISINFO_BODY)
    assert dis.exclamation_ratio > cred.exclamation_ratio


def test_caps_ratio_handles_latin_only() -> None:
    fx = FeatureExtractor(nlp=None)
    # Armenian has no case, so an all-Armenian sentence should yield 0.
    fv = fx.extract(title="ՇՏԱՊ", body_text="Հայաստանի ԱԶԳԱՅԻՆ ժողովը: " * 30)
    assert fv.caps_ratio == 0.0
    # Mixed text with a YELLING Latin term should not be zero.
    fv2 = fx.extract(
        title="x",
        body_text=" ".join(["BREAKING"] * 5 + ["a"] * 5 + ["news"] * 5),
    )
    assert fv2.caps_ratio > 0.0


def test_sentence_complexity_positive(fx: FeatureExtractor) -> None:
    fv = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    assert fv.sentence_complexity > 1.0


def test_headline_body_consistency_in_unit_interval_or_nan(fx: FeatureExtractor) -> None:
    fv = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    v = fv.headline_body_consistency
    assert math.isnan(v) or 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Source signals
# ---------------------------------------------------------------------------
def test_https_flag(fx: FeatureExtractor) -> None:
    fv = fx.extract(title="t", body_text="b" * 500, url="https://armenpress.am/x")
    assert fv.has_https == 1.0
    fv2 = fx.extract(title="t", body_text="b" * 500, url="http://armenpress.am/x")
    assert fv2.has_https == 0.0


def test_alexa_proxy_known_domain(fx: FeatureExtractor) -> None:
    fv = fx.extract(title="t", body_text="b" * 500, url="https://www.azatutyun.am/a/x.html")
    assert fv.alexa_rank_proxy > 0.0


def test_alexa_proxy_unknown_domain(fx: FeatureExtractor) -> None:
    fv = fx.extract(title="t", body_text="b" * 500, url="https://example-fake-site.tk/page")
    assert fv.alexa_rank_proxy == 0.0


def test_mimicry_detects_typosquat(fx: FeatureExtractor) -> None:
    # arrmenpress.am vs armenpress.am should score very high
    fv = fx.extract(title="t", body_text="b" * 500, url="https://arrmenpress.am/x")
    assert fv.subdomain_mimicry_score >= 0.75


def test_mimicry_zero_for_legitimate_host(fx: FeatureExtractor) -> None:
    # A legitimate outlet should never be flagged as mimicking another
    # legitimate sibling on the list.
    fv = fx.extract(title="t", body_text="b" * 500, url="https://armenpress.am/x")
    assert fv.subdomain_mimicry_score == 0.0
    fv2 = fx.extract(title="t", body_text="b" * 500, url="https://www.azatutyun.am/a/x.html")
    assert fv2.subdomain_mimicry_score == 0.0


def test_fake_registry_membership(tmp_path: Path) -> None:
    import json

    fake_file = tmp_path / "fake.json"
    fake_file.write_text(
        json.dumps({"domains": [{"domain": "evil-cnn.tk"}]}),
        encoding="utf-8",
    )
    fx_local = FeatureExtractor(fake_domains=fake_file, nlp=None)
    fv = fx_local.extract(title="t", body_text="b" * 500, url="https://evil-cnn.tk/x")
    assert fv.domain_in_fake_registry == 1.0


# ---------------------------------------------------------------------------
# Quote heuristic
# ---------------------------------------------------------------------------
def test_fabricated_quote_flag_unsourced(fx: FeatureExtractor) -> None:
    body = (
        "Բոլորին զարմացրեց հայտարարությունը: «Մենք պետք է ապստամբենք», - "
        "ասում են, որ ասել է Փաշինյանը: Բայց աղբյուր չկա:"
    )
    # Citation hint "ասում են" is present and resembles a hint -> may not trip.
    # Use a clearly unsourced phrasing instead:
    body2 = "«Մենք պետք է ապստամբենք», - Փաշինյան: Կարդացեք ու տարածեք:"
    fv = fx.extract(title="x", body_text=body2)
    assert fv.fabricated_quote_flag == 1.0


def test_fabricated_quote_flag_sourced(fx: FeatureExtractor) -> None:
    body = (
        "«Մենք պետք է շարունակել բարեփոխումները», - այսօր ասաց Փաշինյանը՝ "
        "ըստ Armenpress լրատվական գործակալության հաղորդագրության:"
    )
    fv = fx.extract(title="x", body_text=body)
    assert fv.fabricated_quote_flag == 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_levenshtein_ratio_identity() -> None:
    assert _levenshtein_ratio("armenpress.am", "armenpress.am") == 1.0


def test_levenshtein_ratio_zero() -> None:
    assert _levenshtein_ratio("abc", "") == 0.0


def test_levenshtein_ratio_near_match() -> None:
    r = _levenshtein_ratio("armenpress.am", "arrmenpress.am")
    assert 0.85 < r < 1.0


# ---------------------------------------------------------------------------
# Red-flag summarisation
# ---------------------------------------------------------------------------
def test_red_flags_fires_on_disinfo(fx: FeatureExtractor) -> None:
    fv = fx.extract(title=DISINFO_TITLE, body_text=DISINFO_BODY)
    flags = fx.red_flags(fv)
    assert any("urgency" in f.lower() or "emotional" in f.lower() for f in flags)


def test_red_flags_quiet_on_credible(fx: FeatureExtractor) -> None:
    fv = fx.extract(title=CREDIBLE_TITLE, body_text=CREDIBLE_BODY)
    flags = fx.red_flags(fv)
    assert len(flags) <= 1  # at most a soft signal
