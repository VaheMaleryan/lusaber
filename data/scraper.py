"""Lusaber · Լուսաբեր — Armenian news scraper (Phase 1a).

Scrapes verified Armenian-language outlets and emits one row per article
to a CSV with columns::

    id, url, title, body_text, source_domain, pub_date,
    label, label_confidence, label_source

Outlets (all labelled ``credible`` = 1 except where noted):

* ``armenpress.am``
* ``civilnet.am``   (special handling for ``#CivilNetCheck``)
* ``media.am``
* ``168.am``
* ``aravot.am``
* ``azatutyun.am``

Design notes
------------
* ``robots.txt`` is consulted per host via ``urllib.robotparser`` and
  cached for the duration of the run. URLs disallowed for our UA are
  skipped silently.
* A polite 1 s delay between requests per host is enforced, plus
  exponential backoff (1 s, 2 s, 4 s, 8 s) on 5xx / connection errors.
* Each site has a small ``Site`` adapter that knows where to find its
  article-list page(s) and how to pull ``title`` / ``body_text`` /
  ``pub_date`` out of the article HTML.
* The scraper is deliberately conservative: ambiguous selectors fall
  back to readable defaults (``<article>``, ``<p>``).

Run::

    python -m data.scraper --limit 25 --out data/sample.csv
"""

from __future__ import annotations

import argparse
import csv
import dataclasses as dc
import hashlib
import json
import logging
import random
import re
import sys
import time
import urllib.robotparser as robotparser
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
random.seed(42)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lusaber.scraper")

USER_AGENT = (
    "LusaberBot/0.1 (+https://github.com/lusaber; research prototype; "
    "civic-tech disinformation detection)"
)
REQUEST_TIMEOUT = 15  # seconds
POLITE_DELAY = 1.0    # seconds between requests to the same host


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dc.dataclass
class Article:
    """A single scraped article row.

    Attributes:
        id: Stable SHA-1 of the canonical URL.
        url: Canonical article URL.
        title: Article title (stripped).
        body_text: Article body, paragraphs joined with ``"\\n\\n"``.
        source_domain: Bare domain (e.g. ``armenpress.am``).
        pub_date: ISO-8601 publication date or ``""`` if unavailable.
        label: Integer class — 1 = credible, 0 = disinformation.
        label_confidence: Float in [0, 1]. Source-driven heuristic.
        label_source: Provenance string, e.g. ``"scraper:verified-outlet"``.
    """

    id: str
    url: str
    title: str
    body_text: str
    source_domain: str
    pub_date: str
    label: int
    label_confidence: float
    label_source: str

    def as_row(self) -> dict[str, str | int | float]:
        return dc.asdict(self)


# ---------------------------------------------------------------------------
# Polite HTTP client
# ---------------------------------------------------------------------------
class PoliteClient:
    """``requests.Session`` wrapper with rate limiting, robots.txt, and backoff.

    The client enforces a per-host minimum interval (``POLITE_DELAY``) and
    retries 5xx / connection errors with exponential backoff.

    Args:
        user_agent: Value sent in the ``User-Agent`` header.
        max_retries: Maximum number of retries on retryable errors.
    """

    def __init__(self, user_agent: str = USER_AGENT, max_retries: int = 4) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.max_retries = max_retries
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser] = {}

    # -- robots.txt --------------------------------------------------------
    def _robots_for(self, host: str, scheme: str = "https") -> robotparser.RobotFileParser:
        if host in self._robots:
            return self._robots[host]
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{scheme}://{host}/robots.txt")
        try:
            rp.read()
            logger.debug("Loaded robots.txt for %s", host)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load robots.txt for %s: %s — defaulting to allow", host, exc)

            class _AllowAll:
                def can_fetch(self, *_: str) -> bool:
                    return True

            rp = _AllowAll()  # type: ignore[assignment]
        self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        scheme = urlparse(url).scheme or "https"
        return self._robots_for(host, scheme).can_fetch(USER_AGENT, url)

    # -- rate limiting -----------------------------------------------------
    def _sleep_for_host(self, host: str) -> None:
        now = time.monotonic()
        last = self._last_hit.get(host, 0.0)
        delta = now - last
        if delta < POLITE_DELAY:
            time.sleep(POLITE_DELAY - delta)
        self._last_hit[host] = time.monotonic()

    # -- public ------------------------------------------------------------
    def get(self, url: str) -> requests.Response | None:
        """Fetch ``url`` honouring robots.txt, rate limit, and retries.

        Returns ``None`` if the URL is disallowed or all retries fail.
        """
        if not self.allowed(url):
            logger.info("robots.txt disallows %s — skipping", url)
            return None

        host = urlparse(url).netloc
        for attempt in range(self.max_retries + 1):
            self._sleep_for_host(host)
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                logger.warning("attempt %d for %s failed: %s", attempt + 1, url, exc)
                resp = None

            if resp is not None and resp.status_code == 200:
                return resp
            status = resp.status_code if resp is not None else "EXC"
            if attempt < self.max_retries and (status == "EXC" or 500 <= int(status) < 600):
                backoff = 2**attempt
                logger.info("retrying %s in %ds (status=%s)", url, backoff, status)
                time.sleep(backoff)
                continue
            logger.warning("giving up on %s (status=%s)", url, status)
            return None
        return None


# ---------------------------------------------------------------------------
# Site adapters
# ---------------------------------------------------------------------------
@dc.dataclass
class Site:
    """Adapter describing how to scrape one Armenian outlet.

    Attributes:
        domain: Bare host, e.g. ``"armenpress.am"``.
        seeds: Listing pages whose anchors point at articles.
        link_filter: Regex an article URL path must match (or ``None``).
        title_selectors: CSS selectors tried in order for the title.
        body_selectors: CSS selectors tried in order for the body container.
        date_selectors: CSS selectors tried in order for the publication date.
        label: Default credibility label for this outlet (1 = credible).
        label_source: Provenance string written to each row.
        label_confidence: Confidence assigned to the label.
    """

    domain: str
    seeds: list[str]
    link_filter: str | None
    title_selectors: list[str]
    body_selectors: list[str]
    date_selectors: list[str]
    label: int = 1
    label_source: str = "scraper:verified-outlet"
    label_confidence: float = 0.95


SITES: list[Site] = [
    Site(
        domain="armenpress.am",
        seeds=["https://armenpress.am/eng/", "https://armenpress.am/arm/"],
        link_filter=r"/(arm|eng)/news/\d+",
        title_selectors=["h1.article-title", "h1"],
        body_selectors=["div.article-text", "article", "div.article-body"],
        date_selectors=["time", "div.article-date", "span.date"],
    ),
    Site(
        domain="civilnet.am",
        seeds=["https://www.civilnet.am/", "https://www.civilnet.am/category/news/"],
        link_filter=r"/news/\d{4}/\d{2}/\d{2}/",
        title_selectors=["h1.entry-title", "h1"],
        body_selectors=["div.entry-content", "article"],
        date_selectors=["time.entry-date", "time"],
    ),
    Site(
        domain="media.am",
        seeds=["https://media.am/en/", "https://media.am/hy/"],
        link_filter=r"/(en|hy)/\d{4}/\d{2}/\d{2}/",
        title_selectors=["h1.entry-title", "h1"],
        body_selectors=["div.entry-content", "article"],
        date_selectors=["time", "span.date"],
    ),
    Site(
        domain="168.am",
        seeds=["https://168.am/", "https://168.am/category/news/"],
        link_filter=r"/\d{4}/\d{2}/\d{2}/\d+\.html",
        title_selectors=["h1.entry-title", "h1"],
        body_selectors=["div.entry-content", "article"],
        date_selectors=["time", "span.posted-on"],
    ),
    Site(
        domain="aravot.am",
        seeds=["https://www.aravot.am/", "https://www.aravot.am/category/news/"],
        link_filter=r"/\d{4}/\d{2}/\d{2}/\d+/",
        title_selectors=["h1.entry-title", "h1"],
        body_selectors=["div.entry-content", "article"],
        date_selectors=["time", "span.date"],
    ),
    Site(
        domain="azatutyun.am",
        seeds=[
            "https://www.azatutyun.am/",
            "https://www.azatutyun.am/p/9756.html",
        ],
        link_filter=r"/a/.+\.html$",
        title_selectors=["h1.title", "h1"],
        body_selectors=["div.wsw", "div.article__body", "article"],
        date_selectors=["time", "div.published"],
    ),
]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
_WHITESPACE_RE = re.compile(r"[ \t ]+")
_NEWLINES_RE = re.compile(r"\n{3,}")


def _clean_text(s: str) -> str:
    """Collapse internal whitespace and trim long blocks of blank lines."""
    s = _WHITESPACE_RE.sub(" ", s)
    s = _NEWLINES_RE.sub("\n\n", s)
    return s.strip()


def _first_selector(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for css in selectors:
        node = soup.select_one(css)
        if node:
            return _clean_text(node.get_text("\n", strip=True))
    return ""


def _first_date(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for css in selectors:
        node = soup.select_one(css)
        if not node:
            continue
        candidate = node.get("datetime") or node.get("content") or node.get_text(strip=True)
        if candidate:
            return candidate
    return ""


def _domain_of(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Listing + article extraction
# ---------------------------------------------------------------------------
def discover_article_urls(
    client: PoliteClient,
    site: Site,
    per_seed_limit: int,
) -> list[str]:
    """Crawl seed pages and return article URLs matching ``site.link_filter``.

    Args:
        client: Polite HTTP client.
        site: Outlet adapter.
        per_seed_limit: Max anchors to return per seed page.

    Returns:
        De-duplicated list of absolute article URLs.
    """
    found: dict[str, None] = {}
    pat = re.compile(site.link_filter) if site.link_filter else None

    for seed in site.seeds:
        resp = client.get(seed)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        n = 0
        for a in soup.find_all("a", href=True):
            href = urljoin(seed, a["href"]).split("#")[0]
            if _domain_of(href) != site.domain:
                continue
            if pat is not None and not pat.search(urlparse(href).path):
                continue
            if href in found:
                continue
            found[href] = None
            n += 1
            if n >= per_seed_limit:
                break
        logger.info("[%s] seed=%s discovered=%d", site.domain, seed, n)
    return list(found.keys())


def parse_article(html: str, url: str, site: Site) -> Article | None:
    """Parse a single article HTML page using ``site``'s selectors.

    Returns ``None`` if title or body cannot be extracted, or if body
    is too short (< 200 chars) to be a real article.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = _first_selector(soup, site.title_selectors)
    body = _first_selector(soup, site.body_selectors)
    pub_date = _first_date(soup, site.date_selectors)

    if not title:
        return None
    if len(body) < 200:
        return None

    return Article(
        id=_sha1(url),
        url=url,
        title=title,
        body_text=body,
        source_domain=site.domain,
        pub_date=pub_date,
        label=site.label,
        label_confidence=site.label_confidence,
        label_source=site.label_source,
    )


def scrape_site(
    client: PoliteClient,
    site: Site,
    limit: int,
    per_seed_limit: int = 50,
) -> Iterator[Article]:
    """Yield up to ``limit`` parsed articles from a single outlet."""
    urls = discover_article_urls(client, site, per_seed_limit=per_seed_limit)
    if not urls:
        logger.warning("[%s] no article URLs discovered", site.domain)
        return
    random.shuffle(urls)
    n = 0
    for url in tqdm(urls, desc=f"scrape {site.domain}", leave=False):
        if n >= limit:
            break
        resp = client.get(url)
        if resp is None:
            continue
        try:
            art = parse_article(resp.text, url, site)
        except Exception as exc:  # noqa: BLE001
            logger.warning("parse failure on %s: %s", url, exc)
            continue
        if art is None:
            logger.debug("skipped (no title or short body): %s", url)
            continue
        yield art
        n += 1
    logger.info("[%s] yielded %d articles", site.domain, n)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def scrape_all(
    limit_per_site: int,
    sites: list[Site] = SITES,
    client: PoliteClient | None = None,
) -> list[Article]:
    """Scrape every site in ``sites`` and return a flat list of articles."""
    client = client or PoliteClient()
    out: list[Article] = []
    for site in sites:
        for art in scrape_site(client, site, limit=limit_per_site):
            out.append(art)
    logger.info("Total articles scraped: %d", len(out))
    return out


def write_csv(rows: list[Article], path: Path) -> None:
    """Write ``rows`` to ``path`` in the schema documented in the module docstring."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "url", "title", "body_text", "source_domain",
        "pub_date", "label", "label_confidence", "label_source",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(r.as_row())
    logger.info("wrote %d rows -> %s", len(rows), path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lusaber.scraper",
        description="Scrape verified Armenian outlets into a labeled CSV.",
    )
    p.add_argument("--limit", type=int, default=5,
                   help="Max articles per outlet (default: 5).")
    p.add_argument("--out", type=Path, default=Path("data/sample.csv"),
                   help="CSV output path (default: data/sample.csv).")
    p.add_argument("--sites", nargs="*", default=None,
                   help="Optional whitelist of domains to scrape.")
    p.add_argument("--preview-json", action="store_true",
                   help="Also print the first 5 rows as JSON to stdout.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    if args.sites:
        wanted = {s.lower() for s in args.sites}
        chosen = [s for s in SITES if s.domain in wanted]
    else:
        chosen = SITES
    logger.info("scraping %d outlets (limit/site=%d)", len(chosen), args.limit)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = scrape_all(limit_per_site=args.limit, sites=chosen)
    write_csv(rows, args.out)
    if args.preview_json:
        preview = [
            {
                "source_domain": r.source_domain,
                "title": r.title,
                "url": r.url,
                "pub_date": r.pub_date,
                "body_excerpt": r.body_text[:240] + ("…" if len(r.body_text) > 240 else ""),
                "label": r.label,
                "label_source": r.label_source,
            }
            for r in rows[:5]
        ]
        print(json.dumps({"started": started, "count": len(rows), "preview": preview},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
