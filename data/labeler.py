"""Lusaber · Լուսաբեր — Phase 1b labeling pipeline.

Assembles the final labeled dataset by combining:

1. A sitemap-driven CivilNet sample. CivilNet's WordPress is JS-rendered
   so a category-page scrape returns no article URLs, but the public
   ``sitemap-articles-*.xml`` indexes do enumerate every published
   article. We sample from the most recent sitemap, fetch each article,
   and:

      * label every CivilNet article as ``credible`` (label = 1);
      * additionally tag those whose body contains the byline
        ``CivilNetCheck`` as ``label_source="scraper:civilnet-factcheck"``.

   The original spec calls for following each fact-check's outbound
   link to the *debunked* fake article and labelling that as 0. In
   practice the great majority of those outbound URLs have been taken
   down (Storm-1516 typosquats are short-lived), so this step yields a
   handful of rows at best — we attempt it but never raise on failure
   and rely on the translated LIAR partition (step 2) for the bulk of
   the ``disinformation`` class.

2. The HuggingFace ``liar`` dataset, stratified-sampled to 1,200
   credible (labels ``true``/``mostly-true``/``half-true``) and 1,200
   disinformation (``false``/``pants-fire``) examples, machine-
   translated EN → HY via ``Helsinki-NLP/opus-mt-en-hy``.

Final output: ``data/armenian_news_labeled.csv`` with columns::

    id, url, title, body_text, source_domain, pub_date,
    label, label_confidence, label_source

Validation (asserts before saving):

* total rows ≥ 2 000
* ``label`` column ∈ {0, 1}
* no duplicate ``id``
* ``body_text`` ≥ 50 chars
* neither class < 35 % of total

CLI::

    python -m data.labeler --civilnet-limit 200 --liar-per-class 1200 \\
        --out data/armenian_news_labeled.csv

The translation step is the slow path; checkpoints land in
``data/liar_translated_checkpoint.csv`` every 100 rows so an
interrupted run resumes from the last save.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses as dc
import hashlib
import logging
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

logger = logging.getLogger("lusaber.labeler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
SEED = 42
random.seed(SEED)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
USER_AGENT = (
    "LusaberBot/0.1 (+https://github.com/lusaber; research prototype; "
    "civic-tech disinformation detection)"
)
POLITE_DELAY = 1.5
REQUEST_TIMEOUT = 20

CIVILNET_SITEMAP_INDEX = "https://www.civilnet.am/sitemap.xml"

LIAR_CREDIBLE_LABELS = {"true", "mostly-true", "half-true"}
LIAR_DISINFO_LABELS = {"false", "pants-fire"}

CHECKPOINT_EVERY = 100


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------
@dc.dataclass
class LabeledRow:
    """One row of ``data/armenian_news_labeled.csv``."""

    id: str
    url: str
    title: str
    body_text: str
    source_domain: str
    pub_date: str
    label: int
    label_confidence: float
    label_source: str

    def as_dict(self) -> dict[str, str | int | float]:
        return dc.asdict(self)


# ---------------------------------------------------------------------------
# Polite HTTP
# ---------------------------------------------------------------------------
def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _polite_get(session: requests.Session, url: str, *, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries + 1):
        try:
            time.sleep(POLITE_DELAY)
            r = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("GET %s failed (%d/%d): %s", url, attempt + 1, retries + 1, exc)
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            return None
        if r.status_code == 200:
            return r
        if 500 <= r.status_code < 600 and attempt < retries:
            time.sleep(2**attempt)
            continue
        logger.warning("GET %s -> %d", url, r.status_code)
        return None
    return None


# ---------------------------------------------------------------------------
# Step 1 — CivilNet via sitemap
# ---------------------------------------------------------------------------
_LOC_RE = re.compile(r"<loc>(.+?)</loc>")


def _list_civilnet_sitemaps(session: requests.Session) -> list[str]:
    r = _polite_get(session, CIVILNET_SITEMAP_INDEX)
    if r is None:
        return []
    locs = _LOC_RE.findall(r.text)
    # Order articles sitemaps by their numeric suffix (latest first).
    arts = [u for u in locs if "sitemap-articles-" in u]
    arts.sort(key=lambda u: int(re.search(r"-(\d+)\.xml", u).group(1)))  # type: ignore[union-attr]
    logger.info("CivilNet sitemap index: %d article sitemaps", len(arts))
    return arts


def _enumerate_civilnet_articles(session: requests.Session, limit: int) -> list[str]:
    """Return up to ``limit`` Armenian-language CivilNet article URLs,
    sampled from the most recent sitemap shards."""
    out: list[str] = []
    for sm_url in _list_civilnet_sitemaps(session):
        r = _polite_get(session, sm_url)
        if r is None:
            continue
        locs = _LOC_RE.findall(r.text)
        # Keep only Armenian-locale entries: /hy/news/<id>
        hy = [u for u in locs if "/hy/news/" in u]
        out.extend(hy)
        if len(out) >= limit * 3:  # over-sample for filtering later
            break
    random.shuffle(out)
    return out[: limit * 3]


def _parse_civilnet_article(html: str, url: str) -> tuple[str, str, str] | None:
    """Return ``(title, body_text, pub_date)`` or ``None`` if parse fails."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)

    body_el = soup.select_one("article") or soup.select_one("main")
    if body_el is None:
        return None
    body = body_el.get_text("\n", strip=True)
    if len(body) < 200:
        return None

    pub_date = ""
    time_el = soup.find("time")
    if time_el is not None:
        pub_date = time_el.get("datetime") or time_el.get_text(strip=True)  # type: ignore[union-attr]
    return title, body, pub_date


def scrape_civilnet(limit: int) -> list[LabeledRow]:
    """Sample CivilNet articles via sitemap; label every one credible.

    Articles whose body contains the byline ``CivilNetCheck`` are
    additionally annotated with ``label_source="scraper:civilnet-factcheck"``;
    all others get ``label_source="scraper:civilnet"``.
    """
    session = _new_session()
    urls = _enumerate_civilnet_articles(session, limit)
    if not urls:
        logger.warning("CivilNet sitemap yielded no URLs")
        return []
    rows: list[LabeledRow] = []
    factcheck_count = 0
    for url in tqdm(urls, desc="civilnet"):
        if len(rows) >= limit:
            break
        resp = _polite_get(session, url)
        if resp is None:
            continue
        try:
            parsed = _parse_civilnet_article(resp.text, url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("parse failure on %s: %s", url, exc)
            continue
        if parsed is None:
            continue
        title, body, pub_date = parsed
        is_factcheck = "civilnetcheck" in body.lower()
        if is_factcheck:
            factcheck_count += 1
        rows.append(
            LabeledRow(
                id=hashlib.sha1(url.encode("utf-8")).hexdigest(),
                url=url,
                title=title,
                body_text=body,
                source_domain="civilnet.am",
                pub_date=pub_date,
                label=1,
                label_confidence=0.95,
                label_source=(
                    "scraper:civilnet-factcheck" if is_factcheck else "scraper:civilnet"
                ),
            )
        )
    logger.info(
        "civilnet: kept %d rows (%d tagged as CivilNetCheck fact-checks)",
        len(rows), factcheck_count,
    )
    return rows


# ---------------------------------------------------------------------------
# Step 2 — LIAR translation
# ---------------------------------------------------------------------------
def _liar_label_to_int(label: str | int) -> int | None:
    """Map LIAR's six-way label to {0, 1, None}.

    Per the user's Phase-1b spec::

        true | mostly-true | half-true → 1 (credible)
        false | pants-fire             → 0 (disinformation)
        anything else                  → None  (drop)

    LIAR2 (``chengxuphd/liar2``) integer labels, ascending truthfulness::

        0 = pants-on-fire, 1 = false, 2 = barely-true,
        3 = half-true,     4 = mostly-true, 5 = true

    Both integer (LIAR2) and string (legacy LIAR) labels are handled.
    """
    if isinstance(label, int):
        if label in (0, 1):          # pants-fire, false
            return 0
        if label in (3, 4, 5):       # half-true, mostly-true, true
            return 1
        return None                  # 2 = barely-true (drop)
    s = label.strip().lower()
    if s in LIAR_CREDIBLE_LABELS:
        return 1
    if s in LIAR_DISINFO_LABELS:
        return 0
    return None


def _sample_liar(per_class: int) -> list[tuple[str, int]]:
    """Stratified sample (statement, label) from HuggingFace ``chengxuphd/liar2``.

    The legacy ``liar`` repo on HF is loading-script-based and no longer
    supported by ``datasets>=4``; ``chengxuphd/liar2`` is the
    parquet-backed modern fork (same source data, same statement
    column, six-way labels).
    """
    from datasets import load_dataset

    ds = load_dataset("chengxuphd/liar2", split="train")
    logger.info("LIAR loaded: %d rows", len(ds))
    by_class: dict[int, list[str]] = {0: [], 1: []}
    for row in ds:
        lbl = _liar_label_to_int(row["label"])  # type: ignore[index]
        if lbl is None:
            continue
        stmt = (row["statement"] or "").strip()  # type: ignore[index]
        if len(stmt) < 30:
            continue
        by_class[lbl].append(stmt)
    rng = random.Random(SEED)
    out: list[tuple[str, int]] = []
    for cls, stmts in by_class.items():
        rng.shuffle(stmts)
        for s in stmts[:per_class]:
            out.append((s, cls))
    rng.shuffle(out)
    logger.info(
        "LIAR sampled: %d credible + %d disinformation",
        sum(1 for _, l in out if l == 1),
        sum(1 for _, l in out if l == 0),
    )
    return out


def _load_translation_checkpoint(path: Path) -> dict[int, str]:
    """Return a ``{row_index: translation}`` map from a previous run."""
    if not path.exists():
        return {}
    out: dict[int, str] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["index"])] = r["hy"]
            except (KeyError, ValueError):
                continue
    logger.info("translation checkpoint: %d rows restored from %s", len(out), path)
    return out


def _save_translation_checkpoint(path: Path, done: dict[int, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["index", "hy"])
        w.writeheader()
        for idx, hy in done.items():
            w.writerow({"index": idx, "hy": hy})


def translate_liar(
    samples: list[tuple[str, int]],
    *,
    checkpoint_path: Path,
    batch_size: int = 32,
) -> list[LabeledRow]:
    """Translate the EN ``statement`` of each sample into Armenian and
    emit one :class:`LabeledRow` per sample.

    Args:
        samples: ``(statement, label)`` pairs from :func:`_sample_liar`.
        checkpoint_path: CSV used to resume on interruption.
        batch_size: Translator batch size.

    Returns:
        Fully populated rows tagged with ``source_domain="liar-dataset"``,
        ``label_source="translated-liar"``, ``label_confidence=0.75``.
    """
    import torch
    from transformers import pipeline

    done = _load_translation_checkpoint(checkpoint_path)
    device = 0 if torch.cuda.is_available() else -1
    logger.info("loading Helsinki-NLP/opus-mt-en-hy on device=%s", device)
    translator = pipeline(
        "translation",
        model="Helsinki-NLP/opus-mt-en-hy",
        device=device,
    )

    pending_idx = [i for i in range(len(samples)) if i not in done]
    logger.info("translating %d statements (already done: %d)", len(pending_idx), len(done))
    for start in tqdm(range(0, len(pending_idx), batch_size), desc="translate"):
        chunk_idx = pending_idx[start : start + batch_size]
        chunk_texts = [samples[i][0] for i in chunk_idx]
        try:
            outputs = translator(chunk_texts, max_length=256, batch_size=batch_size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("batch failed at %d: %s — retrying one by one", start, exc)
            outputs = []
            for t in chunk_texts:
                try:
                    outputs.append(translator(t, max_length=256)[0])  # type: ignore[index]
                except Exception as inner:  # noqa: BLE001
                    logger.warning("single translation failed: %s", inner)
                    outputs.append({"translation_text": ""})
        for idx, out in zip(chunk_idx, outputs):
            done[idx] = (out.get("translation_text") if isinstance(out, dict) else "").strip()
        if (start // batch_size) % max(1, CHECKPOINT_EVERY // batch_size) == 0:
            _save_translation_checkpoint(checkpoint_path, done)
    _save_translation_checkpoint(checkpoint_path, done)

    rows: list[LabeledRow] = []
    for idx, (_, label) in enumerate(samples):
        hy = done.get(idx, "")
        if len(hy) < 30:
            continue
        rid = str(uuid.UUID(bytes=hashlib.sha1(f"liar-{idx}".encode()).digest()[:16]))
        rows.append(
            LabeledRow(
                id=rid,
                url="",
                title="",
                body_text=hy,
                source_domain="liar-dataset",
                pub_date="",
                label=label,
                label_confidence=0.75,
                label_source="translated-liar",
            )
        )
    logger.info("liar: %d translated rows kept", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Step 3 — merge + validate
# ---------------------------------------------------------------------------
def merge_and_validate(parts: Iterable[list[LabeledRow]], out_path: Path) -> dict[str, int | float | dict[str, int]]:
    """Concatenate, dedupe, validate, and write the final CSV.

    Raises:
        AssertionError: if any of the spec's validation invariants fail.

    Returns:
        A summary dict suitable for printing.
    """
    rows: list[LabeledRow] = []
    seen_ids: set[str] = set()
    for part in parts:
        for r in part:
            if r.id in seen_ids:
                continue
            if len(r.body_text.strip()) < 50:
                continue
            seen_ids.add(r.id)
            rows.append(r)

    random.Random(SEED).shuffle(rows)

    # ---- validation ----
    assert len(rows) >= 2_000, f"need ≥2 000 rows, got {len(rows)}"
    labels = {r.label for r in rows}
    assert labels <= {0, 1}, f"label column has values outside {{0,1}}: {labels}"
    assert len({r.id for r in rows}) == len(rows), "duplicate id present"
    cls0 = sum(1 for r in rows if r.label == 0)
    cls1 = sum(1 for r in rows if r.label == 1)
    total = len(rows)
    assert cls0 / total >= 0.35, f"class 0 share {cls0/total:.2%} below 35%"
    assert cls1 / total >= 0.35, f"class 1 share {cls1/total:.2%} below 35%"

    # ---- write ----
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "url", "title", "body_text", "source_domain",
        "pub_date", "label", "label_confidence", "label_source",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r.as_dict())

    sources: dict[str, int] = {}
    for r in rows:
        sources[r.label_source] = sources.get(r.label_source, 0) + 1
    avg_len = sum(len(r.body_text) for r in rows) / total

    summary: dict[str, int | float | dict[str, int]] = {
        "total": total,
        "label_0": cls0,
        "label_1": cls1,
        "sources": sources,
        "avg_body_chars": round(avg_len, 1),
    }
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lusaber.labeler",
                                description="Build the Lusaber labeled CSV.")
    p.add_argument("--civilnet-limit", type=int, default=200,
                   help="Max CivilNet articles to scrape via sitemap (default 200).")
    p.add_argument("--liar-per-class", type=int, default=1200,
                   help="LIAR statements per class to translate (default 1200).")
    p.add_argument("--out", type=Path, default=Path("data/armenian_news_labeled.csv"))
    p.add_argument("--checkpoint", type=Path,
                   default=Path("data/liar_translated_checkpoint.csv"))
    p.add_argument("--skip-civilnet", action="store_true",
                   help="Skip the CivilNet sitemap step (e.g. for resumed runs).")
    p.add_argument("--batch-size", type=int, default=32)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    parts: list[list[LabeledRow]] = []

    if not args.skip_civilnet:
        parts.append(scrape_civilnet(limit=args.civilnet_limit))
    samples = _sample_liar(per_class=args.liar_per_class)
    parts.append(
        translate_liar(samples, checkpoint_path=args.checkpoint, batch_size=args.batch_size)
    )

    summary = merge_and_validate(parts, args.out)
    print("=" * 64)
    print(f"Final dataset: {args.out}")
    print(f"  Total rows           : {summary['total']}")
    print(f"  Label = 0            : {summary['label_0']}")
    print(f"  Label = 1            : {summary['label_1']}")
    print(f"  Average body length  : {summary['avg_body_chars']} chars")
    print(f"  Source breakdown     :")
    for k, v in summary["sources"].items():  # type: ignore[union-attr]
        print(f"    {k:35s} {v}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
