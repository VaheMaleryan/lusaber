"""Lusaber · Լուսաբեր — Gradio demo (Phase 7).

A two-tab Gradio interface that calls the running Lusaber FastAPI
service over HTTP. The demo does NOT import :mod:`api` directly — it
talks to the same public endpoints any external client would, so the
demo doubles as an integration check.

Usage::

    # 1. Start API:  uvicorn api.main:app --reload --port 8000
    # 2. Start demo: python demo/gradio_demo.py
    # 3. Open http://localhost:7860
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import gradio as gr
import requests

logger = logging.getLogger("lusaber.demo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_URL = os.environ.get("LUSABER_API_URL", "http://localhost:8000")
ANALYZE_ENDPOINT = f"{API_URL.rstrip('/')}/analyze"
REQUEST_TIMEOUT = 15

VERDICT_EMOJI = {
    "LIKELY CREDIBLE": "🟢",
    "UNCERTAIN": "🟡",
    "LIKELY DISINFORMATION": "🔴",
}


# ---------------------------------------------------------------------------
# Wire to API
# ---------------------------------------------------------------------------
def call_api(
    text: str,
    url: str,
    title: str,
) -> tuple[float, dict[str, float], dict[str, Any], dict[str, Any], float]:
    """POST to /analyze and return values mapped to the five output widgets.

    Returns:
        ``(credibility_score, verdict_label_dict, source_analysis_json,
        red_flags_json, processing_time_ms)``. On error, returns a
        neutral placeholder so the UI still renders something useful.
    """
    payload: dict[str, Any] = {}
    if text and text.strip():
        payload["text"] = text.strip()
    if url and url.strip():
        payload["url"] = url.strip()
    if title and title.strip():
        payload["title"] = title.strip()

    if not payload.get("text") and not payload.get("url"):
        gr.Warning("Provide at least one of: text, URL.")
        return 0.0, {"—": 1.0}, {}, {}, 0.0

    try:
        resp = requests.post(ANALYZE_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.ConnectionError:
        gr.Warning(
            "API server not running. Start with: "
            "uvicorn api.main:app --reload --port 8000"
        )
        return 0.0, {"API unreachable": 1.0}, {}, {}, 0.0
    except Exception as exc:  # noqa: BLE001
        gr.Warning(f"Request failed: {exc}")
        return 0.0, {"Error": 1.0}, {}, {}, 0.0

    if resp.status_code != 200:
        gr.Warning(f"API returned {resp.status_code}: {resp.text[:300]}")
        return 0.0, {"HTTP error": 1.0}, {}, {}, 0.0

    try:
        data = resp.json()
    except json.JSONDecodeError:
        gr.Warning("API returned non-JSON.")
        return 0.0, {"Invalid response": 1.0}, {}, {}, 0.0

    verdict_text = data.get("verdict", "UNCERTAIN")
    confidence = float(data.get("confidence", 0.0))
    verdict_label = {f"{VERDICT_EMOJI.get(verdict_text, '⚪')} {verdict_text}": confidence}

    return (
        float(data.get("credibility_score", 0.0)),
        verdict_label,
        data.get("source_analysis") or {"note": "URL not provided — no source analysis."},
        {"red_flags": data.get("red_flags", []) or ["— none —"]},
        float(data.get("processing_time_ms", 0.0)),
    )


# ---------------------------------------------------------------------------
# Pre-loaded examples
# ---------------------------------------------------------------------------
# Each example is [text, url, title]. Tagged in comments with the
# expected verdict so users (and the harness) can sanity-check at a glance.

EXAMPLES: list[list[str]] = [
    # 1. LIKELY CREDIBLE — real Armenian text, no URL
    [
        "Հայաստանի կենտրոնական ընտրական հանձնաժողովը հայտնեց, որ 2026 թվականի "
        "խորհրդարանական ընտրությունները տեղի կունենան հունիսի 7-ին, ինչպես "
        "սահմանված է Սահմանադրությամբ: Հանձնաժողովի նախագահը նշեց, որ բոլոր "
        "տեխնիկական նախապատրաստությունները ընթացքի մեջ են:",
        "",
        "ԿԸՀ-ն հայտնեց ընտրությունների ամսաթիվը",
    ],
    # 2. LIKELY CREDIBLE — armenpress.am url
    [
        "Հայաստանի արտգործնախարար Արարատ Միրզոյանն այսօր հանդիպեց Եվրամիության "
        "պատվիրակության հետ Երևանում: Կողմերը քննարկեցին տնտեսական "
        "համագործակցության հարցեր, ինչպես հայտնեց արտգործնախարարությունը: "
        "Հանդիպման ընթացքում Միրզոյանը նշեց, որ Հայաստանը շարունակում է "
        "բարեփոխումների ճանապարհին, հաղորդեց Armenpress լրատվական գործակալությունը:",
        "https://armenpress.am/arm/news/12345",
        "Միրզոյանը հանդիպեց ԵՄ պատվիրակության հետ",
    ],
    # 3. LIKELY DISINFORMATION — ALL-CAPS urgent text + known-fake URL
    [
        "ՇՏԱՊ տարածեք!!! ԲԱՑԱՌԻԿ ԲԱՑԱՀԱՅՏՈՒՄ: Փաշինյանն այսօր ստորագրեց "
        "ԴԱՎԱՃԱՆԱԿԱՆ ու սարսափելի գործարք! «Մենք ստրուկ ենք դարձել», - ասում է "
        "վարչապետը՝ խոստովանելով ողբերգական ճշմարտությունը: Հենց հիմա պետք է "
        "գործել, մինչ ուշ չէ! Փրկեք երկիրը! Տարածեք, մինչ դեռ ուշ չէ!!! "
        "ԲԱՑԱՀԱՅՏԵՔ դավադրությունը!",
        "https://armenpress-news.com/breaking",
        "ՇՏԱՊ ԲԱՑԱՀԱՅՏՈՒՄ Փաշինյանի մասին",
    ],
    # 4. LIKELY DISINFORMATION — known-fake reuters clone
    [
        "ՀՐԱՏԱՊ լուր: Reuters-ի աղբյուրները հաստատում են, որ սարսափելի "
        "գործարք է կնքվել: Բոլորին պետք է զգոն լինել: Մի վստահեք պաշտոնական "
        "աղբյուրներին! Տարածեք այս լուրը հենց հիմա, մինչ դեռ ուշ չէ!",
        "https://reuters-breaking.net/armenia-deal",
        "Reuters: ՀՐԱՏԱՊ լուր Հայաստանից",
    ],
    # 5. LIKELY DISINFORMATION — brand fragment mimicry
    [
        "ԲԱՑԱՌԻԿ լուր CNN-ից! Մեր կորեսպոնդենտները բացահայտել են ցնցող "
        "փաստեր: ՇՏԱՊ տարածեք, մինչ դեռ ուշ չէ: Փրկեք ճշմարտությունը: "
        "Հակառակորդները ուզում են լռեցնել մեզ:",
        "https://armenian-cnn-breaking.tk/exclusive",
        "CNN ԲԱՑԱՌԻԿ բացահայտում",
    ],
    # 6. UNCERTAIN — neutral text, unknown domain
    [
        "Երևանի փոխքաղաքապետը հայտարարեց, որ քաղաքում նոր ճանապարհաշինական "
        "ծրագիր կմեկնարկի առաջիկա ամիսներին: Մանրամասները կհրապարակվեն հաջորդ "
        "շաբաթ տեղի ունենալիք մամուլի ասուլիսի ընթացքում:",
        "https://erevan-news-blog.example/road-plan",
        "Նոր ճանապարհաշինական ծրագիր",
    ],
    # 7. LIKELY DISINFORMATION — emotional/urgency signals only, no URL
    [
        "ՀՐԱՏԱՊ!!! Բոլորին պետք է իմանա այս ողբերգական ճշմարտությունը: "
        "Դավադիր ուժերը ուզում են ոչնչացնել մեր ազգը: Արթնացեք! Ձայն "
        "բարձրացրեք! ՇՏԱՊ տարածեք բոլոր ընկերներին: Մինչ դեռ ուշ չէ, "
        "պետք է գործել: Փրկեք երկիրը դավաճաններից!!! Մի լռեք!",
        "",
        "ՀՐԱՏԱՊ - բոլորին պետք է իմանա",
    ],
    # 8. LIKELY CREDIBLE — azatutyun.am URL
    [
        "Ուկրաինայի զինված ուժերը հարվածել են «Լուկոյլ» ընկերությանը "
        "պատկանող նավթավերամշակման գործարանին, որը գտնվում է Ռուսաստանի "
        "Նիժնի Նովգորոդի մարզում, այսօր հայտնել է Ուկրաինայի գլխավոր շտաբը: "
        "Հաղորդվում է, որ հարվածի հետևանքով գործարանում հրդեհ է բռնկվել:",
        "https://www.azatutyun.am/a/33760878.html",
        "Ուկրաինայի ԶՈՒ-ն հարվածել է ռուսական նավթավերամշակման գործարանին",
    ],
]


# ---------------------------------------------------------------------------
# About tab content
# ---------------------------------------------------------------------------
ABOUT_MARKDOWN = """
### Lusaber · Լուսաբեր

Lusaber ("the one who brings light") is a research prototype that
scores the credibility of Armenian-language news articles and
social-media posts, flags disinformation signals, and exposes networks
of fake sources.

Armenia is the target of a coordinated disinformation campaign
(documented by Microsoft Threat Analysis Center as **Storm-1516**)
in the run-up to the 2026 parliamentary elections. Armenian
fact-checkers — [CivilNetCheck](https://civilnet.am/tag/civilnetcheck/),
media.am, InFact — do this work *manually*, one article at a time.
Lusaber aims to give them, and Armenian citizens, a fast first-pass
signal so disinformation can be intercepted before it spreads.

**Current model: `lusaber-heuristic-v0`** — a deterministic
feature-weighted scorer used while the calibrated XLM-RoBERTa
ensemble (Phase 3) is being trained. Treat scores as hypotheses, not
verdicts.

**Disclaimer.** This is a research prototype. **Not a replacement for
professional fact-checkers.** Always verify with a human editor before
publishing, demoting, or labeling content.
"""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
with gr.Blocks(title="Lusaber · Լուսաբեր") as demo:
    gr.Markdown(
        "# Lusaber · Լուսաբեր\n"
        "_Armenian disinformation detector · Research prototype_"
    )

    with gr.Tabs():
        # ---------- Tab 1: Analyze ----------
        with gr.Tab("Analyze text"):
            with gr.Row():
                with gr.Column(scale=2):
                    in_text = gr.Textbox(
                        label="Armenian text",
                        lines=6,
                        placeholder="Տեղադրեք հոդվածի տեքստը...",
                    )
                    in_url = gr.Textbox(
                        label="Article URL (optional)",
                        placeholder="https://...",
                    )
                    in_title = gr.Textbox(
                        label="Title (optional)",
                        placeholder="Վերնագիր...",
                    )
                    submit = gr.Button("Վերլուծել · Analyze", variant="primary")
                with gr.Column(scale=3):
                    out_score = gr.Number(label="Credibility score (0–100)", precision=2)
                    out_verdict = gr.Label(label="Verdict", num_top_classes=1)
                    out_source = gr.JSON(label="Source analysis")
                    out_flags = gr.JSON(label="Red flags")
                    out_ms = gr.Number(label="Processing time (ms)", precision=2)

            gr.Examples(
                examples=EXAMPLES,
                inputs=[in_text, in_url, in_title],
                label="Pre-loaded examples (mix of credible, uncertain, and disinformation)",
            )

            submit.click(
                fn=call_api,
                inputs=[in_text, in_url, in_title],
                outputs=[out_score, out_verdict, out_source, out_flags, out_ms],
            )

        # ---------- Tab 2: About ----------
        with gr.Tab("About"):
            gr.Markdown(ABOUT_MARKDOWN)


if __name__ == "__main__":
    demo.launch(share=True, server_name="0.0.0.0", server_port=7860)
