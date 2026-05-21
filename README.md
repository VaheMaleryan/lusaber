# Lusaber · Լուսաբեր

> **Making Armenian journalism accessible to diaspora, journalists, and language learners**

Lusaber (*Լուսաբեր*, "the one who brings light") is an Armenian news
summarizer with a built-in source-credibility check. Paste any Armenian
article (or a Russian-language piece from an Armenian outlet) and Lusaber
returns:

* a faithful **bilingual summary** — Armenian + English,
* extracted **named entities** (people, places, organizations),
* topic tags and reading-time estimate,
* a **language-detection** label, and
* the same domain-fingerprinting **source check** that powers Lusaber's
  anti-typosquat subsystem.

---

## The Problem

There are roughly **3 million Armenians in the diaspora** — Los Angeles,
Glendale, Moscow, Paris, Beirut, Buenos Aires — who lost reading fluency in
Armenian a generation or two ago. Their parents read Armenpress, Azatutyun,
CivilNet; they don't. Foreign desks covering the South Caucasus have the same
problem in reverse: the *story* is in Armenian, but the *journalist* isn't.
The same is true for diplomats, NGO researchers, election observers, and
heritage-language learners.

Machine translation alone isn't enough. Word-for-word output from generic MT
mangles Armenian proper nouns, loses register, and produces sentences nobody
wants to read. Lusaber uses a frontier open-weights language model
(Llama 3.3 70B Versatile via Groq's free-tier inference) prompted as an
Armenian-English bilingual desk editor: it produces *newsroom-quality*
summaries — neutral, faithful, attribution-preserving — in both languages
from a single paste.

Lusaber also keeps a **domain-fingerprinting** subsystem from its earlier
disinformation-detection pivot. The text classifier (XLM-RoBERTa fine-tune)
underperformed the F1 ≥ 0.78 target on a noisy translation-heavy dataset and
is no longer surfaced in the UI. But the source check — typosquat detection
against verified Armenian outlets (`armenpress.am`, `civilnet.am`, etc.) and
a registry of known Storm-1516 fakes — works well and remains exposed via the
"Source check" tab.

---

## Target users

* **Diaspora Armenians** rebuilding reading fluency
* **Foreign journalists** covering Armenia / Nagorno-Karabakh / Russia-CSTO
* **Government officials** needing Armenian press in English
* **NGOs and election observers** monitoring Armenian media
* **Heritage-language learners** wanting comprehensible-input alongside source text

---

## Architecture

```
                     ┌──────────────────────────────────┐
                     │     Lusaber · Լուսաբեր pipeline   │
                     └──────────────────────────────────┘

   ┌───────────────┐    ┌────────────────┐    ┌──────────────────┐
   │  Article body │ -> │ Anthropic      │ -> │ Bilingual summary│
   │  (HY / RU)    │    │ Claude Sonnet  │    │ Entities · Topics│
   │               │    │ as Armenian-EN │    │ Reading time     │
   │               │    │ desk editor    │    │ Language detected│
   └───────────────┘    └────────────────┘    └─────────┬────────┘
                                                        │
                  ┌─────────────────────────────────────┘
                  │
                  ▼
   ┌───────────────┐    ┌────────────────┐
   │ URL (optional)│ -> │ SourceAnalyzer │   typosquat / known-fake /
   │               │    │ (Levenshtein + │   brand-fragment detection
   │               │    │  registry)     │   — exposed under /analyze
   └───────────────┘    └────────────────┘     and the Source-check tab
                                                        │
                                                        v
                                              ┌──────────────────┐
                                              │ Credibility 0–100│
                                              │ Verdict + flags  │
                                              │ Source analysis  │
                                              └─────────┬────────┘
                                                        │
                          ┌─────────────────────────────┼────────────┐
                          v                             v            v
                  ┌──────────────┐            ┌─────────────┐   ┌────────────┐
                  │ FastAPI /    │            │ React UI    │   │ Gradio     │
                  │ analyze, etc │            │ (frontend/) │   │ demo       │
                  └──────────────┘            └─────────────┘   └────────────┘
```

---

## Installation

```bash
git clone https://github.com/<you>/lusaber.git
cd lusaber
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download xx_ent_wiki_sm
```

Python 3.10+ required. A CUDA GPU (T4 or better) is strongly recommended for
training; inference runs on CPU.

## Quickstart

```bash
# 0. Groq key (required for /summarize; without it /summarize → HTTP 503)
export GROQ_API_KEY="your-key-here"

# 1. Serve the API
venv/bin/python -m uvicorn api.main:app --reload --port 8000

# 2. Serve the React frontend (separate terminal)
cd frontend && npm install && npm run dev   # → http://localhost:5173

# 3. (Optional) recreate the legacy disinformation-classifier dataset
venv/bin/python -m data.labeler --civilnet-limit 100 --liar-per-class 1200

# 4. (Optional) retrain the legacy XLM-R classifier
bash run_training.sh
```

---

## API

| Method | Path          | Description                                                       |
| ------ | ------------- | ----------------------------------------------------------------- |
| POST   | `/summarize`  | **(primary)** Bilingual summary + entities + topics + source     |
| POST   | `/analyze`    | Domain check; legacy text classifier (hidden from UI)             |
| GET    | `/health`     | Liveness + model-version probe                                    |
| GET    | `/stats`      | Total analyses, model version, uptime                             |
| GET    | `/docs`       | OpenAPI / Swagger UI                                              |

`/summarize` reads `GROQ_API_KEY` from the environment and calls Groq's
free-tier `llama-3.3-70b-versatile` endpoint; it returns HTTP 503 if
the key is missing. Rate limit: 10 req/min/IP. `/analyze` is limited
to 30 req/min/IP. Responses include the header `x-powered-by: Lusaber`.

### Request — `POST /summarize`

```json
{
  "text":  "Հայաստանի կառավարությունը ...",
  "title": "Optional headline",
  "url":   "https://armenpress.am/..."
}
```

### Response — `POST /summarize`

```json
{
  "summary_hy":  "...",
  "summary_en":  "...",
  "headline_en": "...",
  "entities": {
    "people":        ["..."],
    "places":        ["..."],
    "organizations": ["..."]
  },
  "topics":               ["politics", "foreign-policy"],
  "reading_time_minutes": 1.2,
  "language_detected":    "hy",
  "source_check":         { /* same shape as /analyze.source_analysis */ },
  "processing_time_ms":   2934.5,
  "model":                "llama-3.3-70b-versatile"
}
```

## Model card

> **Note on the pivot.** The XLM-RoBERTa text classifier below is the
> *legacy* disinformation-detection model. It still ships with the project
> and the `/analyze` endpoint still returns its score, but the **UI no
> longer surfaces it**: macro-F1 of 0.6554 on the held-out test set was
> below the 0.78 target and the model's outputs are dominated by
> translation artifacts from the LIAR2 → HY MT step. The primary product
> now is the Claude-Sonnet-powered summarizer at `/summarize`; the
> source-fingerprinting subsystem still drives the "Source check" tab.

- **Model identifier**: `lusaber-xlmr-v1`
- **Base**: `xlm-roberta-base` (multilingual, includes Armenian)
- **Task**: binary sequence classification — *credible* vs *disinformation*
- **Training data**: 2,301 rows — 96% translated LIAR2 (EN→HY via
  `Helsinki-NLP/opus-mt-en-hy`) + 100 CivilNet articles via sitemap
  (4 carrying the `CivilNetCheck` byline). Stratified 80/10/10
  split at seed=42 (train 1,840 / val 230 / test 231).

  | Source | Rows | Share |
  |---|---:|---:|
  | `translated-liar` | 2,201 | 95.7% |
  | `scraper:civilnet` | 96 | 4.2% |
  | `scraper:civilnet-factcheck` | 4 | 0.2% |

- **Reported metrics** (held-out test set, n=231):

  | Metric | Value |
  |---|---:|
  | Macro F1 | **0.6554** |
  | Accuracy | 0.6580 |
  | Macro precision | 0.6563 |
  | Macro recall | 0.6551 |
  | ROC-AUC | 0.7069 |
  | Best val F1 (epoch 2) | 0.6682 |
  | Training wall time (CPU M2 Pro) | 646 s (~11 min) |

  Full metrics dump: [`models/checkpoints/training_metrics.json`](models/checkpoints/training_metrics.json).
  Original Phase-5 target was F1 ≥ 0.78; the actual 0.65 is explained
  by the training-data mix being dominated by machine-translated
  LIAR2 (see [MODEL_CARD.md](MODEL_CARD.md) for the full discussion).

- **Limitations**: trained on news-style text — performance on highly
  colloquial social-media Armenian degrades. The model can be fooled by
  well-written disinformation that mimics neutral reporting tone, and it
  cannot verify factual claims against ground truth. MT artifacts in
  the training data (proper-noun mistranslations) cap generalisation.

See [MODEL_CARD.md](MODEL_CARD.md) for the full card.

## Ethical disclaimer

Lusaber is a **research prototype**. Its scores are signals, not verdicts.
Decisions to publish, censor, demote, or label content as disinformation
must remain with human editors and fact-checkers. The system will make
mistakes; treat every prediction as a hypothesis to be checked, not a
conclusion. Always verify with professional fact-checkers
([CivilNet](https://www.civilnet.am), [media.am](https://media.am),
[InFact](https://infact.am)).

## References

- Microsoft Threat Analysis Center, *Storm-1516 Influence Operations*, 2024–2025
- CivilNet, [#CivilNetCheck fact-check archive](https://www.civilnet.am)
- media.am, fact-checking and media-literacy reporting
- CLEF-2023 CheckThat! Lab, *Check-worthiness and verified claim retrieval*
- Wang, W. Y., *"Liar, Liar Pants on Fire": A New Benchmark Dataset for Fake News Detection*, ACL 2017

## License

MIT
