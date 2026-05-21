"""Lusaber · Լուսաբեր — FastAPI integration tests.

Uses an isolated SQLite file under ``tmp_path_factory`` so test runs
don't pollute the developer's local stats counter.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Point the API at an isolated SQLite file *before* importing api.main,
# because the module reads LUSABER_DB at import time.
_TMP_DB = Path(__file__).resolve().parent / "_api_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["LUSABER_DB"] = str(_TMP_DB)

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


CREDIBLE_BODY = (
    "Հայաստանի արտգործնախարար Արարատ Միրզոյանն այսօր հանդիպեց "
    "Եվրամիության պատվիրակության հետ Երևանում: Կողմերը քննարկեցին "
    "տնտեսական համագործակցության հարցեր, ինչպես հայտնեց արտգործնախարարությունը: "
    "Հանդիպման ընթացքում Միրզոյանը նշեց, որ Հայաստանը շարունակում է "
    "բարեփոխումների ճանապարհին, հաղորդեց Armenpress լրատվական գործակալությունը:"
)

DISINFO_BODY = (
    "ՇՏԱՊ տարածեք!!! Փաշինյանն այսօր ստորագրեց ԴԱՎԱՃԱՆԱԿԱՆ ու սարսափելի "
    "գործարք: «Մենք ստրուկ ենք դարձել», - ասում է վարչապետը՝ խոստովանելով "
    "ողբերգական ճշմարտությունը: Հենց հիմա պետք է գործել, մինչ ուշ չէ! "
    "Փրկեք երկիրը! Տարածեք, մինչ դեռ ուշ չէ!!! ԲԱՑԱՀԱՅՏԵՔ դավադրությունը!"
)


# ---------------------------------------------------------------------------
# Health / stats
# ---------------------------------------------------------------------------
def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["name"] == "Lusaber"
    assert body["model_version"]
    assert body["uptime_seconds"] >= 0.0
    assert r.headers.get("x-powered-by") == "Lusaber"


def test_stats(client: TestClient) -> None:
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_analyses"] >= 0
    assert body["name"] == "Lusaber"


# ---------------------------------------------------------------------------
# /analyze
# ---------------------------------------------------------------------------
def test_analyze_requires_text_or_url(client: TestClient) -> None:
    r = client.post("/analyze", json={})
    assert r.status_code == 422


def test_analyze_disinfo_scores_lower_than_credible(client: TestClient) -> None:
    r1 = client.post(
        "/analyze",
        json={"text": CREDIBLE_BODY, "url": "https://armenpress.am/article/1"},
    )
    r2 = client.post(
        "/analyze",
        json={"text": DISINFO_BODY, "url": "https://some-unknown-blog.tk/post"},
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    s1 = r1.json()["credibility_score"]
    s2 = r2.json()["credibility_score"]
    assert s1 > s2, f"credible {s1} should exceed disinfo {s2}"


def test_analyze_returns_verdict_band(client: TestClient) -> None:
    r = client.post(
        "/analyze",
        json={"text": CREDIBLE_BODY, "url": "https://armenpress.am/article/1"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["verdict"] in {"LIKELY DISINFORMATION", "UNCERTAIN", "LIKELY CREDIBLE"}
    assert 0.0 <= j["credibility_score"] <= 100.0
    assert 0.0 <= j["confidence"] <= 1.0
    assert j["model_version"].startswith("lusaber-")
    assert r.headers.get("x-powered-by") == "Lusaber"


def test_analyze_includes_source_when_url(client: TestClient) -> None:
    r = client.post(
        "/analyze",
        json={"text": CREDIBLE_BODY, "url": "https://armenpress.am/article/1"},
    )
    j = r.json()
    assert j["source_analysis"] is not None
    assert j["source_analysis"]["domain"] == "armenpress.am"
    assert j["source_analysis"]["verdict"] == "legitimate"


def test_analyze_omits_source_when_no_url(client: TestClient) -> None:
    r = client.post("/analyze", json={"text": CREDIBLE_BODY})
    j = r.json()
    assert j["source_analysis"] is None


def test_analyze_typosquat_url(client: TestClient) -> None:
    r = client.post(
        "/analyze",
        json={"text": DISINFO_BODY, "url": "https://arrmenpress.am/x"},
    )
    j = r.json()
    assert j["source_analysis"]["verdict"] == "likely-mimicry"
    assert j["credibility_score"] < 40.0


def test_stats_increments(client: TestClient) -> None:
    before = client.get("/stats").json()["total_analyses"]
    client.post(
        "/analyze",
        json={"text": CREDIBLE_BODY, "url": "https://armenpress.am/article/1"},
    )
    after = client.get("/stats").json()["total_analyses"]
    assert after == before + 1


def test_extra_field_rejected(client: TestClient) -> None:
    r = client.post(
        "/analyze",
        json={"text": "hi" * 200, "rogue_field": True},
    )
    assert r.status_code == 422
