"""Lusaber · Լուսաբեր — tests for /feedback + /feedback/stats."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

# Point at an isolated DB *before* importing api.main, just like
# tests/test_api.py and tests/test_summarizer.py do.
_TMP_DB = Path(__file__).resolve().parent / "_feedback_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["LUSABER_DB"] = str(_TMP_DB)

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _payload(rating: int, **overrides):
    base = {
        "session_id": str(uuid.uuid4()),
        "rating": rating,
        "summary_en": "Armenia's foreign minister responded to Putin's EU comment.",
        "article_length": 4085,
        "topics": ["politics", "foreign-policy"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_post_feedback_thumbs_up(client: TestClient) -> None:
    """Happy-path POST inserts a row and returns total_ratings ≥ 1."""
    r = client.post("/feedback", json=_payload(1))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "recorded"
    assert body["total_ratings"] >= 1
    assert r.headers.get("x-powered-by") == "Lusaber"


def test_post_feedback_double_click_is_duplicate(client: TestClient) -> None:
    """Same session + same summary → second call must return 'duplicate'
    without bumping total_ratings."""
    sid = str(uuid.uuid4())
    p = _payload(1, session_id=sid, summary_en="Test summary for de-dup.")
    first = client.post("/feedback", json=p)
    assert first.status_code == 200
    assert first.json()["status"] == "recorded"
    total_after_first = first.json()["total_ratings"]

    second = client.post("/feedback", json=p)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["total_ratings"] == total_after_first


def test_post_feedback_thumbs_down_and_stats(client: TestClient) -> None:
    """A thumbs-down lands in the negative bucket; stats reflect it."""
    client.post("/feedback", json=_payload(-1, summary_en="A different summary."))
    stats = client.get("/feedback/stats")
    assert stats.status_code == 200
    j = stats.json()
    assert j["total_ratings"] >= 1
    assert j["positive"] >= 0
    assert j["negative"] >= 1
    assert 0.0 <= j["positive_rate"] <= 1.0
    assert j["avg_article_length"] > 0


def test_feedback_validates_rating_range(client: TestClient) -> None:
    """Rating must be exactly 1 or -1; anything else is a 422."""
    r = client.post("/feedback", json=_payload(0))
    assert r.status_code == 422
    r2 = client.post("/feedback", json=_payload(2))
    assert r2.status_code == 422
