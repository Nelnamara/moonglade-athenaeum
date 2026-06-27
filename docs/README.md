# 🌙 Moonglade Athenaeum — Documentation

*A library against the Void.*

Moonglade Athenaeum is a local companion for your own [PixAI.art](https://pixai.art)
work — **back up · browse · generate · curate**. It talks to the same API the
website uses (authenticated with *your* API key), pages your entire generation
history at full resolution, keeps a searchable SQLite catalog, serves a local web
gallery, creates new images, and lets you manage both your local archive and your
cloud account.

This tool is **unofficial**. It uses your own credentials, is rate-paced to be
polite to PixAI's servers, and never moves money. PixAI's terms grant you
copyright of your own generations.

---

## The guides

| Guide | What's inside |
|---|---|
| **[Setup](setup.md)** | Install, get an API key, capture the two config values, first run |
| **[Generating](generating.md)** | Create images: model + LoRA pickers, quality mode, priority, aspect, seed |
| **[The Gallery](gallery.md)** | Browse/filter/rate, source & video filters, prompt editing, bulk delete (local + cloud), reconcile, health dashboard |
| **[Architecture](architecture.md)** | How it's built: the three modules, the catalog schema, invariants |
| **[API Operations](../API_OPERATIONS.md)** | The reverse-engineered catalog of PixAI GraphQL operations — the map the client is built from |

## The three faces

- **`pixai_gallery_backup.py`** — the CLI engine (download, organize, generate, sync, delete, reconcile).
- **`pixai_gui.py`** — the PySide6 desktop app (every workflow as a tab + buttons).
- **`pixai_gallery.py`** — the local Flask web gallery + all the SQLite catalog helpers.

## Quick start

```bash
pip install requests pillow PySide6 flask truststore
# copy config.example.json -> config.json, add your PIXAI_API_KEY + USER_ID + hash
python pixai_gui.py                 # the desktop app
# or, headless:
python pixai_gallery_backup.py --update          # grab what's new
python pixai_gallery.py --out pixai_backup       # launch the gallery at :5000
```

See **[Setup](setup.md)** for the details.
