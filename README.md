<div align="center">

# 🌙 Moonglade Athenaeum

### *A library against the Void.*

**Back up · browse · generate · curate** — a complete local companion for **your own** [PixAI.art](https://pixai.art) work.

![Version](https://img.shields.io/github/v/release/Nelnamara/moonglade-athenaeum?color=8839ef) ![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-lightgrey) [![Tests](https://github.com/Nelnamara/moonglade-athenaeum/actions/workflows/tests.yml/badge.svg)](https://github.com/Nelnamara/moonglade-athenaeum/actions/workflows/tests.yml)

*The local web gallery — your entire PixAI history, full-resolution, searchable.*

</div>

---

PixAI's site only shows a handful of images at a time and nothing older is easy to reach. Moonglade Athenaeum talks to the same API your browser uses to pull your **entire** generation history at full resolution, keeps it in a searchable SQLite catalog (prompts, seeds, models, LoRAs, dates), serves a local web gallery, **creates** new images, and helps you prune both your local archive and your cloud account — so nothing is ever lost to the Void.

📖 **[Full documentation lives in the Wiki →](../../wiki)**

---

## ⚡ Quickstart — one key, that's it

```bash
pip install requests pillow flask truststore websockets
```

1. Generate an API key at **[platform.pixai.art](https://platform.pixai.art)** (lifetime up to ~2 years).
2. Copy `config.example.json` to `config.json` and paste your key:
   ```json
   { "PIXAI_API_KEY": "your-key-here" }
   ```
3. Go:
   ```bash
   python pixai_gallery.py --out pixai_backup   # launch the web gallery (browse · generate · curate)
   python pixai_gallery_backup.py --count       # …or headless: how many images you have
   python pixai_gallery_backup.py               # back up everything
   ```
4. First time opening the web gallery: sign in from the machine running the server — the
   login page doubles as an account-creation form the very first time, before any account
   exists (see the [FAQ](../../wiki/FAQ)).

That's the whole setup. Your `USER_ID` is auto-resolved from the key, and everything else has working defaults. No DevTools, no token to recapture. *([Why so simple? →](../../wiki/How-It-Works))*

---

## 🔴 Please read before you run

> [!IMPORTANT]
> **This is a personal-use tool for your *own* PixAI account.** It is built to *preserve and organize what you made* — not to game the platform. It defaults to **cheaper generation priority**, has **no credit-buying or farming automation**, and every destructive action touches **only your own account**. Please keep it that way.

> [!WARNING]
> **"Delete from PixAI" is irreversible.** It deletes the whole task from your cloud account *and* locally. It's gated behind a confirm dialog and typing `DELETE`, but there is no undo on PixAI's side.

> [!NOTE]
> **Your credentials never leave your machine.** `config.json`, `token.txt`, and your backup are git-ignored and local-only. Nothing phones home.

> [!NOTE]
> **Unofficial.** Not affiliated with or endorsed by PixAI. It uses your own API key plus PixAI's private frontend queries, so a major PixAI frontend change *can* break a feature — you'll get a clear error telling you what to recapture. PixAI's terms grant you copyright of your own generations; this tool is rate-paced to be polite to their servers.

---

## ✨ What it can do

| | |
|---|---|
| **Back up everything** | Full-resolution downloads past the gallery limit · fast parallel workers · instant incremental `--update` · deduplicated SQLite catalog · image-to-video backup · published-artwork sync |
| **Browse & search** | Local web gallery: wildcard prompt search, model/LoRA/tag/rating filters, date pickers, lightbox, ZIP export, saved views, privacy blur, mobile/PWA |
| **Generate** | Full creation suite in the **web gallery** (dockable drawer: image · edit/enhance/fix · video with gallery-picked references), plus a matching CLI — model + LoRA pickers, live cost preview, and **free generation cards auto-apply** so covered gens cost 0 credits; results drop straight into your catalog. **The Loom** is a full video storyboard tool built on top of it, for multi-shot sequences with continuity |
| **Curate** | **Collections** (group images/videos without moving files) · **Select mode** with drag-paint multi-select · star ratings · inline prompt edit · bulk find/replace · the **Folio of Honors** tracks achievements as your archive grows |
| **Stay in sync** | Instant incremental updates · live **event watch** (`--watch --watch-backup` auto-collects finishing gens) · bulk delete locally or cloud-side · `--reconcile-deleted` for cloud-deleted orphans · Collection Health dashboard |
| **Run & control** | Web **Control Panel**: one-click maintenance jobs with a real progress bar and a Stop button, scheduled auto-backups, and **server Stop/Restart from the browser** · double-click `Serve Gallery` launcher · **make it yours**: drop your own header marks into `pixai_backup/branding/marks/` and pick one + its animation, then set the Desktop launcher icon to match (none ship — bring your own art) |

---

## 📚 Documentation

Everything deep lives in the **[Wiki](../../wiki)**:

[Setup & Configuration](../../wiki/Setup) · [Backing Up](../../wiki/Backing-Up) · [The Gallery](../../wiki/Gallery) · [Generating Images](../../wiki/Generating) · [The Loom](../../wiki/The-Loom) · [Collections & Curation](../../wiki/Collections) · [Deleting & Cloud Sync](../../wiki/Deleting) · [Collection Health](../../wiki/Health) · [Control Panel](../../wiki/Control-Panel) · [Folio of Honors](../../wiki/Folio-of-Honors) · [Troubleshooting](../../wiki/Troubleshooting) · [Trust & Safety](../../wiki/Trust-and-Safety) · [FAQ](../../wiki/FAQ) · [How It Works](../../wiki/How-It-Works)

In-repo: [`docs/architecture.md`](docs/architecture.md) (how it's built), [`docs/LOOM.md`](docs/LOOM.md) (the Loom's manual), [`docs/STATE.md`](docs/STATE.md) (current project state), [`docs/STANDARDS.md`](docs/STANDARDS.md) (house standards), [`docs/ART.md`](docs/ART.md) (art direction), and [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Requirements

`requests` is the only hard dependency. `pillow` (thumbnails/convert), `flask` (gallery), `truststore` (HTTPS behind AV/proxies), and `websockets` (`--watch` and the gallery's live-mirror) are recommended; `ffmpeg` on PATH is required for the Loom's export and frame handoff, and optional for video posters.

```bash
pip install requests pillow flask truststore websockets
```

---

<div align="center">
<sub>Unofficial · personal-use · <a href="LICENSE">MIT licensed</a>. Made for Nelnamara's archive, shared in case it helps yours.</sub>
</div>
