# Lusaber · Լուսաբեր — Model Card

**Model identifier:** `lusaber-xlmr-v1`
**Released:** 2026-05
**License:** MIT
**Maintainer:** Lusaber project (`maleryanvahe4@gmail.com`)

---

## Model summary

A binary credibility classifier for Armenian-language news articles
and social-media posts, fine-tuned from **`xlm-roberta-base`**. Given
an article's title and body, the model emits a probability that the
text is credible (vs. disinformation). The Lusaber API maps that
probability to a 0–100 credibility score and one of three verdicts
(`LIKELY DISINFORMATION`, `UNCERTAIN`, `LIKELY CREDIBLE`).

The model is *one* signal inside a larger system. The Lusaber API
also applies source-fingerprinting clamps (known-fake domains and
typosquats can hard-cap the score) and surfaces feature-based red
flags (urgency lexicon, all-caps density, fabricated-quote heuristic,
WHOIS-derived domain age) to the user. **The transformer alone is
not the verdict.**

## Intended use

- First-pass triage for Armenian journalists and fact-checkers.
- Plumbing inside the Lusaber Gradio demo and FastAPI service.
- Research baseline for future Armenian disinformation detectors.

## Out-of-scope use

- **Not a fact-checker.** The model classifies *style*, not *truth*.
- Not for moderation decisions without a human in the loop.
- Not for non-news Armenian text (literature, transcripts, IM chats).
- Not for languages other than Armenian.

## Training data

| Source | Rows | Share | Label confidence |
|---|---:|---:|---:|
| `translated-liar` (LIAR2 EN→HY via `Helsinki-NLP/opus-mt-en-hy`) | 2,201 | 95.7% | 0.75 |
| `scraper:civilnet` (CivilNet sitemap-driven scrape) | 96 | 4.2% | 0.95 |
| `scraper:civilnet-factcheck` (CivilNet articles bylined `CivilNetCheck`) | 4 | 0.2% | 0.95 |
| **Total** | **2,301** | 100% | — |

- Class balance: 1,076 disinformation (46.8%) / 1,225 credible (53.2%).
- Split: stratified 80 / 10 / 10 (train 1,840 / val 230 / test 231) at `random_state=42`.
- Body length: min 50, mean 208, max 14,302 characters.

See `data/labeler.py` for the full Phase-1b pipeline (CivilNet
sitemap → fact-check byline filter → LIAR2 sample → opus-mt-en-hy
translation → merge/validate).

## Training

| Hyperparameter | Value |
|---|---:|
| Base model | `xlm-roberta-base` |
| Task | sequence classification, `num_labels=2` |
| Tokenizer max length | 512 |
| Input format | `title + " [SEP] " + body_text[:1000]` |
| Epochs | 3 |
| Per-device train batch size | 1 |
| Gradient accumulation | 32 |
| Effective batch size | 32 |
| Learning rate | 2e-5 |
| Warmup ratio | 0.1 |
| Weight decay | 0.01 |
| Scheduler | cosine |
| FP16 | False |
| Seed | 42 |
| Device | CPU (forced, no MPS) on M2 Pro |
| Wall time | ~11 min |

The bs=1 / accum=32 split is unusual; it was forced by an Apple MPS
allocator OOM that fired during the initial run with bs=4. CPU-only
training with effective batch 32 reproduced the same gradient profile
without touching MPS.

## Evaluation

Held-out test set (n=231):

| Metric | Value |
|---|---:|
| **Macro F1** | **0.6554** |
| Accuracy | 0.6580 |
| Macro precision | 0.6563 |
| Macro recall | 0.6551 |
| ROC-AUC | 0.7069 |
| Best epoch (by val F1) | epoch 2 |
| Best val F1 | 0.6682 |

The original Phase-5 target of F1 ≥ 0.78 was **not** met. The gap is
explained primarily by the training-data composition (see
"Limitations" below). The model is shipped anyway as the v1 baseline;
the heuristic scorer (`lusaber-heuristic-v0`) remains in the system
as an automatic fallback when the trained model can't be loaded.

## Limitations

- **MT noise dominates the training signal.** 96% of training rows
  are LIAR2 statements translated from English to Armenian via
  `Helsinki-NLP/opus-mt-en-hy`. The MT model regularly mangles proper
  nouns (`Trump → Թալմուդ`/Talmud, `Voter → Վիքիփեդիա`/Wikipedia,
  `Jed Bundy → Ջոդ Բենդի`). The classifier partly learns those
  artifacts as class features rather than Armenian disinformation
  patterns, which (a) caps generalisation, and (b) means short clean
  Armenian text gets near-50/50 predictions.

- **Tiny native-Armenian sample.** Only ~100 CivilNet rows are
  natively Armenian. Of those, just 4 carry the explicit
  `CivilNetCheck` byline. The disinformation class has effectively
  *zero* native examples — all label=0 rows are translated LIAR2.

- **Style ≠ truth.** The model classifies surface style; a confident,
  well-written falsehood will not be caught. Domain signals
  (`known-fake`, `likely-mimicry`) are the system's primary defense
  against that.

- **No social-media calibration.** Training is news-style text. Tweets,
  Telegram posts, and short messages degrade performance.

- **Election-context drift.** Trained 2026-05; if the 2026 Armenian
  election cycle introduces new political vocabulary, retrain.

## Ethical considerations

- **Human in the loop is mandatory.** Lusaber is a triage signal, not
  a verdict. Editorial decisions, takedowns, and labels must remain
  with a human fact-checker.
- **Asymmetric error costs.** A false-credible reading lets
  disinformation through; a false-disinfo reading silences a real
  voice. The API surfaces both the score and the red-flag rationale
  so downstream UI can present a defensible explanation rather than a
  single number.
- **Source-based hard caps.** The API caps scores for known-fake
  (`≤ 5`) and likely-mimicry (`≤ 30`) domains, and floors them at 70
  for verified-outlet domains. This means the trained model cannot
  unilaterally rehabilitate a domain in our registry, nor can it
  alone condemn a verified outlet.

## How to load (Python)

```python
from api.analyzer import TrainedModelScorer, HeuristicScorer

scorer = TrainedModelScorer(fallback_scorer=HeuristicScorer())
fv, source = ...  # see api/analyzer.py
score, confidence, version = scorer.score(
    fv, source,
    title="...", body_text="...",
)
print(scorer.using_trained, version)
# True  lusaber-xlmr-v1
```

## How to reproduce

```bash
# Phase 1b — build the dataset (~14 min on CPU)
venv/bin/python -m data.labeler --civilnet-limit 100 --liar-per-class 1200

# Phase 3 — train (~11 min on CPU, M2 Pro)
bash run_training.sh
```

## Citation

Wang, W. Y. *"Liar, Liar Pants on Fire": A New Benchmark Dataset for Fake News Detection.* ACL 2017.

Conneau, A. et al. *Unsupervised Cross-lingual Representation Learning at Scale (XLM-R).* ACL 2020.

Tiedemann, J., Thottingal, S. *OPUS-MT: Building open translation services for the World.* EAMT 2020.

CivilNetCheck fact-check archive: <https://civilnet.am/tag/civilnetcheck/>

Microsoft Threat Analysis Center, *Storm-1516 Influence Operations*, 2024–2025.
