<!--
Lusaber · Լուսաբեր — Issue template.
Thanks for reporting! Please fill in as much as you can; the items
marked (required) are the ones that meaningfully shorten the
investigation. Delete the section that doesn't apply.
-->

## Type
<!-- (required) Tick one -->
- [ ] Bug — something broke
- [ ] Documentation — README/MODEL_CARD/inline docs are wrong or unclear
- [ ] Feature request — new capability
- [ ] Performance — slow or timing out
- [ ] Source registry — propose adding / removing a fake domain (please include citation)

---

## Where did you see it?
<!-- (required) -->
- [ ] Live demo — https://vahemaleryan.github.io/lusaber
- [ ] Live API — https://lusaber-api-production.up.railway.app
- [ ] Local self-host
- [ ] Other (please describe)

---

## What you did
<!-- (required) Steps to reproduce. Be specific. -->

1.
2.
3.

## What you expected

## What actually happened

---

## Inputs
<!-- (required for bugs in /summarize or /analyze) -->

- Endpoint:   `POST /summarize` | `POST /analyze` | other
- `text` (first ~200 chars):
- `url` (if any):
- `title` (if any):
- API response status / body (paste the JSON):

```json
{}
```

---

## Environment

- Browser (for frontend bugs):
- Backend version (`GET /health` → `model_version`):
- Date/time of the request (so we can correlate logs):

---

## Anything else?
<!-- screenshots, terminal output, hunches, related issues -->
