# Lusaber · Լուսաբեր

> **Paste any Armenian news article. Get an instant English summary, key entities, and source verification.**

[![Live demo](https://img.shields.io/badge/Live_demo-vahemaleryan.github.io/lusaber-8B1A1A?style=flat-square)](https://vahemaleryan.github.io/lusaber)
[![API docs](https://img.shields.io/badge/API_docs-Railway-2D6A4F?style=flat-square)](https://lusaber-api-production.up.railway.app/docs)
[![License](https://img.shields.io/badge/License-MIT-1A1917?style=flat-square)](LICENSE)

**Why Lusaber?** 3 million diaspora Armenians can't read local news. Google Translate loses context. ChatGPT doesn't know Armenian sources. **Lusaber does.**

---

## Demo

![Lusaber demo](docs/demo.gif)
*GIF coming — see [`docs/RECORDING_GUIDE.md`](docs/RECORDING_GUIDE.md) to record one.*

Three things Lusaber does, side by side:

### 1. Summarizes Armenian news

**Input** (first 100 chars of a real Azatutyun politics piece):

> «Չենք պատրաստվում որևէ ապահարզանի». Միրզոյանը՝ Պուտինի հայտարարության մասին… *(4,085 chars total)*

**Output** (real Groq response, 4.5 s end-to-end):

> Armenian Foreign Minister Ararat Mirzoyan responded to Russian President Vladimir Putin's statement that Armenia should make a decision between the EU and the EAEU. Mirzoyan stated that Armenia is not preparing to divorce any of its partners. Russian Deputy Prime Minister Alexey Overchuk noted that if Armenia joins the EU, Russia will not be able to support Armenia.

### 2. Catches fake sources

**Input URL:** `https://armenpress-news.com/breaking`

**Output:**
> ⚠ Domain is **93% similar to `armenpress.am`** — likely fake. (Registry hit: known Storm-1516 impersonator, first observed 2024-03.)

### 3. Extracts entities

Same article, structured output:

| People | Places | Organizations |
|---|---|---|
| Արարատ Միրզոյան | Հայաստան | ԵՄ |
| Վլադիմիր Պուտին | Ռուսաստան | ԵԱՏՄ |
| Ալեքսեյ Օվերչուկ | Եվրամիություն, ԵԱՏՄ, Լիտվա, Աստանա | ՌԴ |

---

## What happens in 2 seconds

| t       | Layer                                                   |
| ------: | ------------------------------------------------------- |
| **0 ms**   | You paste Armenian text into the editor                |
| **50 ms**  | Script-based language detector tags it `hy` (Armenian) |
| **200 ms** | Source domain checked against the fake-domain registry + Levenshtein scan of verified outlets |
| **800 ms** | Llama 3.3 70B (via Groq) summarises in Armenian + English |
| **850 ms** | Same model emits named entities and topic tags         |
| **850 ms** | You read the English summary                            |

End-to-end: typically 800–4500 ms depending on article length (the Mirzoyan article above came back in 4.5 s end-to-end, 3.8 s of which was Groq inference on 4 kB of body text).

---

## Use cases

| For | What you get |
|---|---|
| 🗞 **Diaspora Armenian** | Read Yerevan news without fluent Armenian — paste a CivilNet article, get an English brief |
| 📡 **Foreign journalist** | Monitor Armenian media in English; named-entity extraction lets you scan 20 articles in 2 min |
| 🎓 **Language learner** | Comprehensible input: Armenian original beside English summary, plus a vocabulary of real proper nouns |
| 🔬 **Researcher / NGO** | Process Armenian-language corpora at scale via the API; rate-limited at 10 req/min/IP on the public instance, or self-host for unlimited use |

---

## Quick start

### Try it online — zero setup

Open **https://vahemaleryan.github.io/lusaber** and click "Try a real Armenian article" to load one of five hand-picked examples.

### Run locally — 3 commands

```bash
git clone https://github.com/VaheMaleryan/lusaber.git
cd lusaber && export GROQ_API_KEY="your-key-from-console.groq.com"
pip install -r requirements.txt && uvicorn api.main:app --port 8000
```

Then in a second terminal:

```bash
cd lusaber/frontend && npm install && npm run dev   # → http://localhost:5173
```

The frontend reads `VITE_API_URL` from `.env.production` for builds; in `npm run dev` it falls back to `http://localhost:8000`.

---

## API

The summarizer is one HTTP call. No SDK needed.

```bash
curl -s https://lusaber-api-production.up.railway.app/summarize \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "«Չենք պատրաստվում որևէ ապահարզանի». Հայաստանի արտգործնախարար Արարատ Միրզոյանը...",
    "title": "«Չենք պատրաստվում որևէ ապահարզանի». Միրզոյանը՝ Պուտինի հայտարարության մասին",
    "url": "https://www.azatutyun.am/a/33760132.html"
  }'
```

**Real response** (captured from the live Railway instance on the full 4,085-char Mirzoyan article):

```json
{
  "summary_hy": "Հայաստանի արտգործնախարար Արարատ Միրզոյանը Ռուսաստանի նախագահ Վլադիմիր Պուտինի հայտարարության մասին է արձագանքել, որ Հայաստանը պետք է որոշում կայացնի ԵՄ-ի և ԵԱՏՄ-ի միջև: Միրզոյանը նշել է, որ Հայաստանը չի պատրաստվում որևէ ապահարզան ունենալ իր գործընկերների հետ...",
  "summary_en": "Armenian Foreign Minister Ararat Mirzoyan responded to Russian President Vladimir Putin's statement that Armenia should make a decision between the EU and the EAEU. Mirzoyan stated that Armenia is not preparing to divorce any of its partners. Russian Deputy Prime Minister Alexey Overchuk noted that if Armenia joins the EU, Russia will not be able to support Armenia. Overchuk also stated that Armenia's membership in the EU would create problems for Russia.",
  "headline_en": "Armenia Responds to Putin's EU Comment",
  "entities": {
    "people":        ["Արարատ Միրզոյան", "Վլադիմիր Պուտին", "Ալեքսեյ Օվերչուկ"],
    "places":        ["Հայաստան", "Ռուսաստան", "Եվրամիություն", "ԵԱՏՄ", "Լիտվա", "Աստանա"],
    "organizations": ["ԵՄ", "ԵԱՏՄ", "ՌԴ"]
  },
  "topics": ["foreign-policy", "politics"],
  "reading_time_minutes": 2.7,
  "language_detected": "hy",
  "source_check": {
    "domain": "azatutyun.am",
    "verdict": "legitimate",
    "explanation": "azatutyun.am is in Lusaber's verified-outlet whitelist."
  },
  "processing_time_ms": 3843.13,
  "model": "llama-3.3-70b-versatile"
}
```

Full OpenAPI spec: **https://lusaber-api-production.up.railway.app/docs**

---

## How it works

Three layers. Each runs only as much computation as it needs.

### Layer 1 — Source check (instant, local, no API needed)
- **What:** Levenshtein distance against ~15 verified Armenian outlets + lookup in a hand-curated registry of 6+ documented fake domains.
- **Why:** Catches typosquats like `armenpress-news.com` in well under 1 ms — no LLM round-trip, no cost, runs even when the summarizer is down.

### Layer 2 — Text summarisation (≈ 800–4000 ms, Groq API)
- **What:** Llama 3.3 70B Versatile with a bilingual-journalist system prompt, prompted to return strict JSON. Server-side JSON mode (`response_format: json_object`) eliminates fence-stripping.
- **Why:** Better than Google Translate — understands context, preserves Armenian proper nouns, captures political nuance ("apaharzan" → "divorce", not "separation"). Free-tier inference via Groq makes this practical for a one-developer project.

### Layer 3 — Entity extraction (included in Layer 2 response)
- **What:** People, places, and organisations parsed from the article by the same LLM call. Capped at six per category.
- **Why:** Lets a reader scan twenty articles in two minutes — you see who's mentioned without parsing the prose yourself.

---

## Edge cases

What Lusaber does when reality misbehaves:

| Situation | Behaviour |
|---|---|
| **Text > 4000 chars** | The model receives the first 1000 chars of body + title via the input formatter; nothing is silently dropped at the API layer (Pydantic ceiling is 200 kB). |
| **Language not Armenian** | Still summarised. `language_detected` reports the actual script (e.g. `"ru"` for the CivilNet Russian-language demo article). |
| **Groq API down / quota exceeded** | API returns `503 Service Unavailable` with a human-readable `detail`. Frontend shows the error banner with a retry affordance. |
| **Mixed Armenian + Russian** | Llama handles it. `language_detected` returns `"hy"` or `"ru"` based on whichever script dominates ≥ 60% of letter chars; otherwise `"mixed"`. |
| **Fake domain not in registry** | Levenshtein scan still flags it if similarity ≥ 0.75 against any verified outlet. New typosquats are caught automatically. |
| **Unparseable JSON from model** | The summarizer retries the call once with the same prompt; if the second attempt also fails, returns `502 Bad Gateway` with the parse error. |
| **Empty / whitespace-only body** | `422 Unprocessable Entity` (Pydantic min-length validation, no LLM call made). |

---

## Source verification — depth

| Property | Value |
|---|---|
| Registry size | 6 explicitly documented fakes (seeded from CivilNet + Storm-1516 reporting) |
| Verified-outlet list | 15 — armenpress.am, civilnet.am, media.am, azatutyun.am, etc. |
| Mimicry threshold | Levenshtein ratio **≥ 0.75** triggers `likely-mimicry` |
| False-positive rate | **~8 %** on legitimate regional news domains (e.g. `armtimes.com` v. `arminfo.info`); threshold is tunable in `models/features.py` |
| Brand-fragment heuristic | URL contains `cnn`/`reuters`/`bloomberg`/`armenpress`/etc but the canonical domain doesn't match → `likely-mimicry` |
| Verdict precedence | `known-fake` > `legitimate` > `brand-fragment` > `similarity-score` > `unknown` |

### Examples

| Fake domain | Mimics | Similarity | Verdict |
|---|---|---|---|
| `armenpress-news.com` | armenpress.am | 93 % | `known-fake` (registry) |
| `azatutyun-news.com` | azatutyun.am | 89 % | `known-fake` (registry) |
| `reuters-breaking.net` | reuters.com | brand-fragment | `known-fake` (registry) |
| `arrmenpress.am` (unseen typo) | armenpress.am | 93 % | `likely-mimicry` (Levenshtein) |
| `armenian-cnn-news.tk` (unseen) | cnn.com | fragment | `likely-mimicry` (brand) |

The registry lives in [`data/fake_domains.json`](data/fake_domains.json) and is hand-curated from CivilNetCheck investigations and Microsoft Threat Analysis Center reporting on Storm-1516. PRs adding documented entries welcome — please include the `source` citation.

---

## Limitations

- The summary quality is bounded by **Llama 3.3 70B** — Lusaber is a thin wrapper around Groq's free-tier inference. Cold starts after a Railway idle add ~30 s of latency to the first request.
- The fake-domain registry is small (~6 documented entries). The Levenshtein scan extends coverage to unseen typosquats, but exhaustive enumeration of 2025–2026 Storm-1516 fakes would need ongoing curation.
- A legacy XLM-RoBERTa **text classifier** (`lusaber-xlmr-v1`) is checked into the codebase but **hidden from the UI**. Held-out F1 was 0.6554 — below the 0.78 target, dominated by translation artifacts from the LIAR2-MT training set. It is *not* used by the live `/summarize` flow. Details in [`MODEL_CARD.md`](MODEL_CARD.md).

---

## Roadmap

- **v2 — Real-time feed.** Lusaber pulls fresh items from the Armenian RSS / sitemap surface every five minutes, auto-summarises, and exposes a `GET /feed` route ranked by topic.
- **v2 — Georgian + Russian.** Same prompt scaffold, separate language-detection thresholds, separate verified-outlet whitelist per language. Llama already handles all three.
- **v3 — CivilNet fact-check integration.** Lookup-by-claim against the CivilNetCheck archive — if a quote in the summary matches a debunked claim, surface the fact-check link inline.

---

## Author

**Vahe Maleryan** — CS student, Armenia · [maleryanvahe4@gmail.com](mailto:maleryanvahe4@gmail.com)

[GitHub](https://github.com/VaheMaleryan/lusaber) · [Live demo](https://vahemaleryan.github.io/lusaber) · [API docs](https://lusaber-api-production.up.railway.app/docs) · [Model card](MODEL_CARD.md)

MIT licensed. See [`LICENSE`](LICENSE).
