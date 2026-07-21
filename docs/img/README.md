# Screenshots for the README / Wiki

This folder is the landing spot for screenshots. It is **empty on purpose** — no images
have been captured yet.

> **Adding a PNG here is not enough to make it appear anywhere.** An earlier version of
> this file promised the README "already references them, so they'll light up the moment
> the files exist." That stopped being true when commit `d699bcc` stripped the five
> screenshot tags out of `README.md`, and no images ever arrived to replace them. Today
> **nothing** in the repo references this folder, so adding a file also means adding the
> `![...](docs/img/<name>.png)` reference wherever you want it shown.

## Shot list (the spec, if/when you capture them)

Aim for ~1400px wide, pick light **or** dark theme and stay consistent, and crop out your
OS chrome.

| File | Shot | Notes |
|---|---|---|
| `hero.png` | The gallery grid, full of thumbnails | The banner. Make it look abundant — lots of images, filter bar visible. |
| `curation.png` | Select mode active + a Collection | Toggle **Select**, paint a few selected (highlighted), Collection dropdown open or a collection filtered. |
| `generate.png` | The web **Generate drawer** | Prompt filled, a model chosen, LoRA row visible. |
| `health.png` | `/health` Collection Health page | Scroll so a chart + the top-models/word-cloud show. |

Optional GIFs (nice-to-have): `drag-paint.gif` (painting a selection),
`generate-appear.gif` (submit → image appears in the grid). ScreenToGif (Windows) or
similar; keep them short and under ~5 MB.

After adding files: `git add docs/img/*.png`, add the markdown references, and commit.
