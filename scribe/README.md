# Scribe — private handwriting capture, transcription & search

A small self-hosted app for a law office that needs to digitize handwritten
notes **without anything leaving the building**:

- **Capture:** open the app in the iPhone's browser (Safari) over the office
  Wi-Fi and tap *Scan a page* — it opens the camera directly. No iOS app, no
  App Store, no cloud.
- **Transcribe:** a local open-source vision model (via [Ollama](https://ollama.com))
  reads the handwriting on the PC and produces an editable transcript.
- **Store & search:** images and transcripts live in a SQLite database and a
  folder on the PC's disk (`scribe/data/`). Full-text search (SQLite FTS5)
  works across titles, matter/case names, and transcripts — including Hebrew,
  since FTS5's unicode tokenizer is language-agnostic.

Nothing in this app talks to the internet. The only network traffic is
phone → PC over your LAN, and app → Ollama on the same machine.

## Quick start (Docker, recommended)

On the office PC (Windows with Docker Desktop, Mac, or Linux):

```bash
cd scribe
docker compose up -d --build

# one-time: download the OCR model into the local Ollama (~6 GB)
docker compose exec ollama ollama pull qwen3-vl:8b
```

Then find the PC's LAN IP (e.g. `192.168.1.50`) and on the iPhone open:

```
http://192.168.1.50:8000
```

Tip: add it to the Home Screen in Safari (Share → *Add to Home Screen*) and it
behaves like an app.

## Quick start (no Docker)

```bash
# 1. install Ollama from https://ollama.com and pull a vision model
ollama pull qwen3-vl:8b

# 2. run the app
cd scribe
pip install -r requirements.txt
python app.py
```

## Configuration (environment variables)

| Variable          | Default                  | Purpose |
|-------------------|--------------------------|---------|
| `SCRIBE_PASSWORD` | *(unset = no login)*     | Shared office password — set this. |
| `SCRIBE_PORT`     | `8000`                   | HTTP port. |
| `SCRIBE_DATA_DIR` | `scribe/data`            | Where images + database are stored. **Back this folder up.** |
| `OCR_ENGINE`      | `ollama`                 | `ollama` or `none` (manual typing only). |
| `OLLAMA_URL`      | `http://localhost:11434` | Where Ollama runs. |
| `OLLAMA_MODEL`    | `qwen3-vl:8b`            | Any Ollama vision model. |
| `OLLAMA_TIMEOUT`  | `600`                    | Seconds to wait per page. |

## Choosing a model

Handwriting is hard for classic OCR (Tesseract etc. are built for print);
open-weight **vision-language models** are currently the best local option:

| Model               | Size   | Notes |
|---------------------|--------|-------|
| `qwen3-vl:8b`       | ~6 GB  | Default. Strong handwriting OCR; its OCR officially covers 32 languages **including Hebrew**. Needs ~8 GB RAM/VRAM. |
| `qwen3-vl:4b`       | ~3 GB  | For weaker PCs; less accurate on messy writing. |
| `qwen3-vl:32b`      | ~21 GB | Best quality if you have a big GPU (24 GB+). |
| `qwen2.5vl:7b`      | ~6 GB  | Previous generation; fine for English, weaker on Hebrew. |

### A note on Hebrew handwriting

Expect English handwriting to work well out of the box. Hebrew is harder:
modern cursive Hebrew letterforms differ completely from print, and little
training data exists for them — this is a known weak spot for *every* OCR
system, not just local ones. Realistic expectations: neat Hebrew block
writing should produce a usable draft with `qwen3-vl`; real Israeli cursive
will need significant correction. Two mitigations are built into the
workflow: every transcript is reviewed/edited before saving, and each
corrected page you save is effectively a labeled training example — if the
firm later wants higher Hebrew accuracy, the accumulated image+transcript
pairs in `data/` are exactly what's needed to fine-tune a model on the
specific handwriting of the firm's own attorneys.

A PC with a mid-range NVIDIA GPU (or an Apple Silicon Mac) transcribes a page
in seconds; CPU-only works but takes a minute or more per page. Every
transcript is editable in the UI — treat the model output as a first draft and
proofread anything that matters legally.

## Daily use

1. Tap **Scan a page**, photograph the document (good light, page flat,
   fill the frame), optionally add a title and matter/case, upload.
2. OCR runs in the background; the page refreshes itself when the transcript
   is ready. Edit and **Save** — saving also updates the search index.
3. **Search** from the bar at the top; results show highlighted snippets.
   Prefix matching is automatic (`depos` finds `deposition`).

## Privacy & operations notes

- **Set `SCRIBE_PASSWORD`** so only staff on the Wi-Fi can open it, and keep
  the office Wi-Fi WPA2/3-protected. For traffic encryption on the LAN, put
  the app behind a reverse proxy with a self-signed cert (e.g. Caddy), or run
  it on a Tailscale-style private network for out-of-office access.
- **Backups:** everything is in the `data/` folder (images + `scribe.db`).
  Copy it anywhere — that's a complete backup.
- Do **not** port-forward this app to the public internet.
