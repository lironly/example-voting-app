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

## The knowledge vault (Karpathy's LLM-wiki pattern)

The vault follows [Andrej Karpathy's LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
plain Markdown, no vector database, agentic retrieval.

```
data/vault/
  CLAUDE.md    schema — conventions & workflows, readable by any agent
  index.md     auto-maintained catalog: every doc + one-line summary, by matter
  log.md       append-only, greppable activity log
  raw/         immutable approved transcripts (Scribe writes, never edits)
  wiki/        curated synthesis pages (matter summaries) — grows over time
```

When a transcript has been proofread, hit **✓ Approve → knowledge base**.
The document is published under `raw/<matter>/`, the index is rebuilt, and
the local model writes a one-line summary for the catalog. Example file:

```markdown
---
id: scribe-12
title: "Meeting notes"
matter: "Cohen v. Levi"
type: handwritten-note
source: scribe
source_image: images/1781272749_68326373.jpg
scanned_at: "2026-06-12 13:59:09"
status: approved
---

Client agreed to reschedule the deposition to July 3rd.
```

The vault is the firm's canonical, tool-agnostic knowledge store:

- **Plain files, organized by matter.** Browse or edit them with
  [Obsidian](https://obsidian.md) (local-only), sync the folder to the office
  file server, back it up like any folder.
- **One convention, many sources.** Scribe notes are the first source; other
  ingestion jobs (emails, filings, memos) can write the same
  frontmatter format into the same vault, and everything downstream — search,
  RAG, matter timelines — works uniformly.
- **Approval is the quality gate.** Only human-reviewed text enters the
  vault, so anything an AI later retrieves from it is trustworthy.

Set `SCRIBE_VAULT_DIR` to point the vault at a shared/synced location.

Because the vault is self-describing (`CLAUDE.md`), you can also open it
directly with Claude Code or any agent and ask questions, run a periodic
"lint pass" (find contradictions, stale claims, matters missing a wiki
page), or build curated `wiki/` pages — the schema file tells the agent how.

## Ask the firm (💬 Ask)

The **Ask** page answers questions from the vault using Karpathy-style
agentic retrieval, fully locally:

1. The local model reads `index.md` and picks the most relevant documents
   (at most `ASK_MAX_FILES`, default 6).
2. Only those files are loaded, and the model answers **with citations to
   the file paths it used** — or says the vault doesn't contain the answer.

No embeddings, no vector index to keep in sync: the index *is* the catalog,
and it is regenerated on every approval. This scales comfortably to the
thousands of documents a boutique firm accumulates; if the index ever
outgrows the model's context window, that's the point to add a search step
(FTS5 keyword pre-filter — already built in — or embeddings) in front of it.

Answers are AI-generated drafts: always check the cited source documents
before relying on them professionally.

## Privacy & operations notes

- **Set `SCRIBE_PASSWORD`** so only staff on the Wi-Fi can open it, and keep
  the office Wi-Fi WPA2/3-protected. For traffic encryption on the LAN, put
  the app behind a reverse proxy with a self-signed cert (e.g. Caddy), or run
  it on a Tailscale-style private network for out-of-office access.
- **Backups:** everything is in the `data/` folder (images + `scribe.db`).
  Copy it anywhere — that's a complete backup.
- Do **not** port-forward this app to the public internet.
