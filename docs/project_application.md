# Lusaber · Լուսաբեր — Project Application

**Applicant:** Vahe Maleryan
**Sector:** AI / ML
**Project:** Lusaber · Լուսաբեր

---

## 1. One-sentence pitch *(≤ 20 words)*

Lusaber turns Armenian news into faithful English summaries — so 3 million diaspora Armenians and foreign journalists can read Yerevan.

---

## 2. Problem *(≤ 150 words)*

My grandmother left Yerevan in 1989. Her son — my father — reads Armenian. I read it slowly. My cousins in Los Angeles don't read it at all. We lost a language in three generations, and with it, the daily news from home.

There are about three million Armenians in the diaspora. Most can't access local news in real time. Meanwhile, the Storm-1516 Russian disinformation network is targeting Armenia ahead of the June 2026 parliamentary elections — Microsoft Threat Analysis Center, Recorded Future, and CivilNet have documented dozens of impersonator domains (`armenianinsider.am`, `dailyarmenia.am`, `greenarmenia.org`, `courrierfrance24.fr`). Google Translate mangles Armenian proper nouns. ChatGPT doesn't know Armenian sources. Armenian fact-checkers — CivilNetCheck, media.am, InFact — do the work manually, one article at a time. A whole class of readers and a whole class of disinformation go unread.

---

## 3. Solution *(≤ 150 words)*

**Live now: <https://vahemaleryan.github.io/lusaber>**

Paste any Armenian news article. In under five seconds Lusaber returns:

- a faithful bilingual summary (Armenian + English) by Llama 3.3 70B (Groq free tier), prompted as an Armenian-English desk editor;
- people, places, and organizations extracted as structured data;
- topic tags + reading-time estimate;
- a domain check against a 42-entry registry of documented Storm-1516 fakes plus a Levenshtein scan against verified Armenian outlets.

Better than Google Translate because Lusaber understands context, Armenian proper nouns, and political nuance. Better than ChatGPT because the source-credibility layer catches typosquats like `arrmenpress.am` (96% similarity to `armenpress.am`) in under a millisecond, before any LLM call. Built with 67 passing tests, a public API, and a 42-domain fake registry sourced from real investigations.

---

## 4. Why you *(≤ 100 words)*

I'm a Computer Science student in Armenia. I've been building Lusaber alone for the last month — the FastAPI backend, the React frontend, the Groq integration, the source-fingerprinting subsystem, the testing harness, the demo. I shipped it because I needed it: I read Armenian news for my family in Los Angeles and Glendale who can't. I understand the gap between an Armenian newsroom and a diaspora reader because I sit at both ends of it every week. That first-hand understanding is what makes the prompts, the verified-outlet whitelist, and the fact-checker citations real instead of theoretical.

---

## 5. Traction *(≤ 50 words)*

- **Live product**, deployed: <https://vahemaleryan.github.io/lusaber>
- **Public API**, auto-deploys on push: <https://lusaber-api-production.up.railway.app/docs>
- **GitHub**, MIT-licensed: <https://github.com/VaheMaleryan/lusaber>
- **67/67 passing tests** (`pytest`)
- **42 documented Storm-1516 / CopyCop domains** in the registry, every entry cited

---

## 6. Roadmap *(≤ 100 words)*

**v2 — Real-time news feed.** Lusaber pulls fresh items from Armenian RSS / sitemap surfaces every five minutes, auto-summarises, and exposes a ranked feed by topic. Goal: a diaspora reader opens Lusaber in the morning and sees yesterday's Yerevan in English in under a minute.

**v2 — Georgian and Russian.** Same prompt scaffold, separate language-detection thresholds, separate verified-outlet whitelist per language. Llama already handles all three; this is mostly editorial work.

**v3 — CivilNet fact-check integration.** When a Lusaber summary contains a claim CivilNetCheck has already debunked, surface the fact-check link inline. Closes the loop between summarisation and verification.

---

## 7. What I'm looking for

Three concrete things:

1. **Mentorship** from people who have shipped news / civic-tech products in the South Caucasus. I've built v1 alone; v2 needs editorial judgment I don't have yet.
2. **Connections** at CivilNet, media.am, InFact, and the Microsoft Threat Analysis Center — for the fact-check integration and to keep the fake-domain registry current.
3. **Honest feedback** on the product. A startup competition or any community of builders is full of people who can tell me — kindly — what's wrong with Lusaber after they try it. That's what I want most.

I'll bring a working demo, the GitHub repo, and a willingness to ship faster than the disinformation does.

---

## Links

- Live demo · <https://vahemaleryan.github.io/lusaber>
- API docs · <https://lusaber-api-production.up.railway.app/docs>
- GitHub · <https://github.com/VaheMaleryan/lusaber>
- Model card · [`MODEL_CARD.md`](../MODEL_CARD.md)
- Contact · <maleryanvahe4@gmail.com>
