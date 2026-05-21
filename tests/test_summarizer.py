"""Lusaber · Լուսաբեր — tests for the summarizer service.

All tests inject a mock Anthropic client via the ``client_factory``
hook in :class:`api.summarizer.Summarizer` and via a per-test
fixture in the FastAPI integration tests. Nothing in this file hits
the network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from api.summarizer import (
    Summarizer,
    SummarizerFailed,
    SummarizerUnavailable,
    _coerce_json,
    _detect_language,
    _reading_time_minutes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
CANNED_PAYLOAD = {
    "summary_hy": "Հայաստանի վարչապետը այսօր հանդիպեց ԵՄ պատվիրակության հետ Երևանում:",
    "summary_en": "Armenia's prime minister met with an EU delegation in Yerevan today.",
    "headline_en": "Armenian PM hosts EU delegation in Yerevan",
    "entities": {
        "people": ["Նիկոլ Փաշինյան"],
        "places": ["Երևան", "Հայաստան"],
        "organizations": ["Եվրամիություն"],
    },
    "topics": ["politics", "foreign-policy"],
    "language_detected": "hy",
}

ARTICLE_HY = (
    "Հայաստանի վարչապետ Նիկոլ Փաշինյանն այսօր հանդիպեց Եվրամիության "
    "պատվիրակության հետ Երևանում: Կողմերը քննարկեցին տնտեսական "
    "համագործակցության հարցեր, ինչպես հաղորդեց վարչապետի գրասենյակը:"
)


@dataclass
class _MockMessage:
    content: str


@dataclass
class _MockChoice:
    message: _MockMessage


@dataclass
class _MockResponse:
    choices: list[_MockChoice]


class _ScriptedClient:
    """Records ``chat.completions.create`` calls and returns scripted
    texts in order. Shape mirrors the Groq SDK's OpenAI-style namespace:

        client.chat.completions.create(...)  →  .choices[0].message.content
    """

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls: list[dict[str, Any]] = []
        # Mimic SDK namespace by aliasing back to self at each level.
        self.chat = self
        self.completions = self
        self.created = 0

    def create(self, **kwargs: Any) -> _MockResponse:
        self.calls.append(kwargs)
        if not self._texts:
            text = "{}"
        else:
            text = self._texts.pop(0)
        self.created += 1
        return _MockResponse(choices=[_MockChoice(message=_MockMessage(content=text))])


def _client_factory(texts: list[str]):
    client = _ScriptedClient(texts)
    return client, lambda: client


# ---------------------------------------------------------------------------
# Tests — pure helpers
# ---------------------------------------------------------------------------
def test_detect_language_armenian() -> None:
    assert _detect_language("Հայաստանի կառավարությունը") == "hy"


def test_detect_language_russian() -> None:
    assert _detect_language("Премьер-министр Армении встретился сегодня") == "ru"


def test_detect_language_english() -> None:
    assert _detect_language("The prime minister of Armenia met today") == "en"


def test_detect_language_mixed() -> None:
    # Roughly equal Armenian + English → "mixed"
    text = "Lusaber Լուսաբեր Armenia Հայաստան " * 5
    assert _detect_language(text) == "mixed"


def test_reading_time_short() -> None:
    assert _reading_time_minutes("one two three") < 1.0


def test_reading_time_long() -> None:
    text = " ".join(["word"] * 1000)
    assert _reading_time_minutes(text) >= 4.0


# ---------------------------------------------------------------------------
# Tests — JSON coercion
# ---------------------------------------------------------------------------
def test_coerce_json_raw() -> None:
    assert _coerce_json('{"a": 1}') == {"a": 1}


def test_coerce_json_fenced() -> None:
    blob = 'Some preamble\n```json\n{"a": 2}\n```\nepilogue'
    assert _coerce_json(blob) == {"a": 2}


def test_coerce_json_brace_span() -> None:
    blob = 'Here is what I found: {"a": 3, "b": "ok"} (end)'
    assert _coerce_json(blob) == {"a": 3, "b": "ok"}


def test_coerce_json_failure() -> None:
    with pytest.raises(json.JSONDecodeError):
        _coerce_json("no json here at all")


# ---------------------------------------------------------------------------
# Tests — Summarizer
# ---------------------------------------------------------------------------
def test_summarizer_unavailable_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = Summarizer()
    assert s.available is False
    with pytest.raises(SummarizerUnavailable):
        s.summarize(text=ARTICLE_HY)


def test_summarizer_available_with_factory() -> None:
    _, factory = _client_factory([json.dumps(CANNED_PAYLOAD)])
    s = Summarizer(client_factory=factory)
    assert s.available is True


def test_summarizer_happy_path() -> None:
    client, factory = _client_factory([json.dumps(CANNED_PAYLOAD)])
    s = Summarizer(client_factory=factory)
    result = s.summarize(text=ARTICLE_HY, title="t", url="https://armenpress.am/x")
    assert result.summary_hy.startswith("Հայաստանի")
    assert result.summary_en.startswith("Armenia's")
    assert result.headline_en == "Armenian PM hosts EU delegation in Yerevan"
    assert result.entities["people"] == ["Նիկոլ Փաշինյան"]
    assert "politics" in result.topics
    assert result.language_detected in {"hy", "ru", "en", "mixed"}
    assert result.source_check is not None
    assert result.source_check.verdict == "legitimate"
    assert result.processing_time_ms >= 0.0
    assert result.model == "llama-3.3-70b-versatile"
    assert client.created == 1


def test_summarizer_no_source_check_when_url_missing() -> None:
    _, factory = _client_factory([json.dumps(CANNED_PAYLOAD)])
    s = Summarizer(client_factory=factory)
    result = s.summarize(text=ARTICLE_HY)
    assert result.source_check is None


def test_summarizer_retries_once_on_bad_json() -> None:
    client, factory = _client_factory(
        ["this is not json at all", json.dumps(CANNED_PAYLOAD)]
    )
    s = Summarizer(client_factory=factory)
    result = s.summarize(text=ARTICLE_HY)
    assert client.created == 2
    assert result.summary_hy != ""


def test_summarizer_gives_up_after_second_failure() -> None:
    _, factory = _client_factory(["no json", "still no json"])
    s = Summarizer(client_factory=factory)
    with pytest.raises(SummarizerFailed):
        s.summarize(text=ARTICLE_HY)


def test_summarizer_rejects_empty_text() -> None:
    _, factory = _client_factory([json.dumps(CANNED_PAYLOAD)])
    s = Summarizer(client_factory=factory)
    with pytest.raises(ValueError):
        s.summarize(text="   ")


def test_summarizer_caps_entity_lists() -> None:
    payload = dict(CANNED_PAYLOAD)
    payload["entities"] = {
        "people": [f"person{i}" for i in range(20)],
        "places": [f"place{i}" for i in range(20)],
        "organizations": [f"org{i}" for i in range(20)],
    }
    _, factory = _client_factory([json.dumps(payload)])
    s = Summarizer(client_factory=factory)
    result = s.summarize(text=ARTICLE_HY)
    assert len(result.entities["people"]) == 6
    assert len(result.entities["places"]) == 6
    assert len(result.entities["organizations"]) == 6


# ---------------------------------------------------------------------------
# Tests — FastAPI /summarize endpoint (uses TestClient already in test_api.py)
# ---------------------------------------------------------------------------
# Point the API at an isolated DB; tests for /summarize must not collide
# with the existing test_api.py's DB.
_TMP_DB = Path(__file__).resolve().parent / "_summarizer_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["LUSABER_DB"] = str(_TMP_DB)

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture
def client_no_key(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A test client with no GROQ_API_KEY in the environment."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_with_summarizer(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A test client where Summarizer has a scripted client injected."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _, factory = _client_factory([json.dumps(CANNED_PAYLOAD)])
    # Override the app's Summarizer with one that uses our scripted client.
    with TestClient(app) as c:
        c.app.state.summarizer = Summarizer(client_factory=factory)
        yield c


def test_endpoint_503_when_no_key(client_no_key: TestClient) -> None:
    r = client_no_key.post(
        "/summarize",
        json={"text": ARTICLE_HY, "url": "https://armenpress.am/x"},
    )
    assert r.status_code == 503, r.text
    assert "GROQ_API_KEY" in r.json()["detail"]


def test_endpoint_happy_path(client_with_summarizer: TestClient) -> None:
    r = client_with_summarizer.post(
        "/summarize",
        json={
            "text": ARTICLE_HY,
            "title": "Միրզոյանը հանդիպեց ԵՄ պատվիրակության հետ",
            "url": "https://armenpress.am/article/1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary_hy"].startswith("Հայաստանի")
    assert body["summary_en"].startswith("Armenia's")
    assert body["headline_en"]
    assert body["entities"]["people"] == ["Նիկոլ Փաշինյան"]
    assert body["source_check"]["verdict"] == "legitimate"
    assert body["language_detected"] in {"hy", "ru", "en", "mixed"}
    assert body["model"] == "llama-3.3-70b-versatile"
    assert r.headers.get("x-powered-by") == "Lusaber"


def test_endpoint_requires_text(client_with_summarizer: TestClient) -> None:
    r = client_with_summarizer.post("/summarize", json={"url": "https://armenpress.am/x"})
    assert r.status_code == 422


def test_endpoint_rejects_extra_fields(client_with_summarizer: TestClient) -> None:
    r = client_with_summarizer.post(
        "/summarize",
        json={"text": ARTICLE_HY, "rogue": True},
    )
    assert r.status_code == 422
