"""Lusaber · Լուսաբեր — tests for :class:`models.features.SourceAnalyzer`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.features import SourceAnalyzer


def _make(tmp_path: Path, fakes: list[str] | None = None) -> SourceAnalyzer:
    p = tmp_path / "fake.json"
    p.write_text(
        json.dumps({"domains": [{"domain": d} for d in (fakes or [])]}),
        encoding="utf-8",
    )
    return SourceAnalyzer(fake_domains=p)


def test_legitimate_outlet_verdict(tmp_path: Path) -> None:
    sa = _make(tmp_path)
    r = sa.analyze("https://armenpress.am/article/1")
    assert r.verdict == "legitimate"
    assert r.is_legitimate_outlet is True
    assert r.matched_domain is None
    assert r.similarity_score == 0.0


def test_known_fake_verdict(tmp_path: Path) -> None:
    sa = _make(tmp_path, fakes=["fake-cnn.tk"])
    r = sa.analyze("https://fake-cnn.tk/breaking")
    assert r.verdict == "known-fake"
    assert r.in_fake_registry is True


def test_typosquat_verdict(tmp_path: Path) -> None:
    sa = _make(tmp_path)
    r = sa.analyze("https://arrmenpress.am/article")
    assert r.verdict == "likely-mimicry"
    assert r.matched_domain == "armenpress.am"
    assert r.similarity_score >= 0.75


def test_brand_fragment_verdict(tmp_path: Path) -> None:
    sa = _make(tmp_path)
    r = sa.analyze("https://armenian-cnn-news.tk/article")
    assert r.verdict == "likely-mimicry"
    assert r.brand_fragment_match == "cnn.com"


def test_unknown_verdict(tmp_path: Path) -> None:
    sa = _make(tmp_path)
    r = sa.analyze("https://some-random-blog-9472.example/post")
    assert r.verdict == "unknown"


def test_serializable(tmp_path: Path) -> None:
    sa = _make(tmp_path)
    r = sa.analyze("https://armenpress.am/x")
    d = r.as_dict()
    # round-trip through json should not raise
    json.dumps(d)


def test_known_fake_beats_legitimate(tmp_path: Path) -> None:
    # If, somehow, a legitimate outlet appeared in the fake registry,
    # the fake verdict should win (defensive precedence).
    sa = _make(tmp_path, fakes=["armenpress.am"])
    r = sa.analyze("https://armenpress.am/x")
    assert r.verdict == "known-fake"
