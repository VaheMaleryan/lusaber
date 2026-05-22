# How to record `docs/demo.gif`

The README links to `docs/demo.gif` directly under the header. This
guide describes exactly how to produce it — repeatable and ~5 min of
real work.

## Specs

| Property      | Value                                   |
|---------------|-----------------------------------------|
| Resolution    | **1200 × 800 px**                        |
| Duration      | **≈ 30 s** (keep it tight — don't ramble) |
| Frame rate    | 15 fps (Kap default; balance smoothness vs file size) |
| Output size   | Aim for **≤ 6 MB** so GitHub renders the GIF inline |
| File path     | `docs/demo.gif`                         |

## Tools

- **Recommended: [Kap](https://getkap.co)** (free, Mac, captures any
  region, exports GIF directly with size budget).
- Or **QuickTime → screen recording → MOV**, then convert with
  [ffmpeg](https://ffmpeg.org):
  ```bash
  ffmpeg -i demo.mov -vf "fps=15,scale=1200:-1:flags=lanczos" \
    -loop 0 docs/demo.gif
  ```

## Shot list

Time   | What happens on screen
------:| ---
 0:00  | Browser at `https://vahemaleryan.github.io/lusaber` — empty Summarize tab visible
 0:02  | Click **"Try a real Armenian article"** (the disclosure under the form)
 0:04  | Click the **"Credible · Armenian government brief"** preset — the textarea fills with the Mirzoyan / Putin article in Armenian
 0:06  | Click **"Ամփոփել · Summarize"**
 0:07  | Three skeleton cards appear on the right (loading state)
 0:10  | Skeletons fade out, real cards fade in with the staggered animation:
       |   • English headline (Playfair Display)
       |   • Bilingual summary (cream HY panel · white EN panel)
 0:14  | Pause for ~3 s on the summaries card so the viewer can read at least the English block
 0:18  | Scroll slowly down to reveal the **Entities** card (People · Places · Organizations as pills)
 0:22  | Continue scrolling to the **Topics + Source** card — topic pills (`politics`, `foreign-policy`) on the left, the green `LEGITIMATE` source pill for `azatutyun.am` on the right
 0:28  | Hold for 2 s on the bottom of the page, then end
 0:30  | End of GIF

## Capture region

Crop tightly. The 1200 × 800 frame should contain:
- the top header (`Lusaber · Լուսաբեր`)
- both tab pills
- the form + the entire right-column results stack

Hide your browser bookmarks bar (`Cmd ⌘ + Shift + B`) to reclaim
vertical pixels. Use Chrome / Safari (not Firefox — Vite's hot-reload
chrome shows up in dev but you'll be on the live gh-pages site anyway).

## Where the GIF goes in the README

Already wired — `README.md` references `docs/demo.gif` directly under
the badges row:

```md
## Demo

![Lusaber demo](docs/demo.gif)
*GIF coming — see `docs/RECORDING_GUIDE.md` to record one.*
```

Once `docs/demo.gif` lands, drop the placeholder line. Push to `main`
and the GIF will render inline on the GitHub repo page within seconds
(GitHub caches GIF assets aggressively — append `?v=2` to the path if
you re-record and need to bust the cache).

## Bonus: a still frame for social cards

While you're recording, also grab one PNG at the moment the results
are fully visible (around `t = 0:18`) and save it as
`docs/demo-screenshot.png`. Use it as the OG / Twitter card image
when you tweet the project — small (~120 KB), no animation, but
captures the wow.
