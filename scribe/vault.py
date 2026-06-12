"""Knowledge vault following Andrej Karpathy's LLM-wiki pattern.

Layout (all plain files under SCRIBE_VAULT_DIR):
  CLAUDE.md   schema: conventions + workflows, so any agent (Claude Code, a
              local model) knows how to query and maintain the vault
  index.md    catalog of every document with a one-line summary, by matter;
              agents read this FIRST, then open only the relevant files
  log.md      append-only, greppable activity log
  raw/        immutable approved transcripts (Scribe writes, never edits)
  wiki/       curated synthesis pages (matter summaries etc.), agent-maintained

Scribe is one ingestion source; other sources (emails, filings) should write
to raw/ with the same frontmatter and update index.md + log.md the same way.
"""
import os
import re
from datetime import date

import db

VAULT_DIR = os.environ.get("SCRIBE_VAULT_DIR", os.path.join(db.DATA_DIR, "vault"))

SCHEMA_FILE = """# Firm Knowledge Vault — schema

This folder is the firm's knowledge base, structured per Karpathy's LLM-wiki
pattern. If you are an AI agent working in this folder, follow these rules.

## Layers
- `raw/<matter>/` — immutable source documents (approved transcripts of
  handwritten notes, later: emails, filings). Read, never edit.
- `wiki/` — curated synthesis pages you may create and maintain
  (e.g. one page per matter: current state, open issues, key decisions).
- `index.md` — catalog of every document with a one-line summary, grouped
  by matter. Keep it in sync whenever raw/ or wiki/ changes.
- `log.md` — append-only log, entries like `## [2026-06-12] ingest | Title (Matter)`.

## Conventions
- Every file is Markdown with YAML frontmatter: `id`, `title`, `matter`,
  `type`, `source`, dates. Hebrew and English content are both expected.
- File names: `<slug-of-title>-<id>.md` inside a matter folder.

## Workflows
- **Query:** read `index.md` first, open only the relevant files, answer
  with citations to file paths. Never answer from memory alone; if the
  vault has nothing, say so.
- **Ingest:** new raw documents arrive via the Scribe app (which updates
  index.md and log.md automatically). When ingesting manually, follow the
  same convention.
- **Lint pass (periodic):** look for contradictions between documents,
  stale claims superseded by newer ones, and matters missing a wiki page;
  report findings, do not silently rewrite raw/.

## Confidentiality
Everything here is privileged attorney work product. It must never be sent
to external services; only local tools and models may process it.
"""


def _slug(text, fallback):
    """Filesystem-safe name that keeps Unicode (e.g. Hebrew) letters."""
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", "-", text)
    return text[:80] or fallback


def _yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def init():
    os.makedirs(os.path.join(VAULT_DIR, "raw"), exist_ok=True)
    os.makedirs(os.path.join(VAULT_DIR, "wiki"), exist_ok=True)
    schema_path = os.path.join(VAULT_DIR, "CLAUDE.md")
    if not os.path.exists(schema_path):
        with open(schema_path, "w", encoding="utf-8") as f:
            f.write(SCHEMA_FILE)


def publish(doc):
    """Write the document under raw/; returns the path relative to VAULT_DIR."""
    init()
    matter_dir = _slug(doc["matter"], "_unfiled")
    name = f"{_slug(doc['title'], 'note')}-{doc['id']}.md"
    rel_path = os.path.join("raw", matter_dir, name)

    front = "\n".join([
        "---",
        f"id: scribe-{doc['id']}",
        f"title: {_yaml_str(doc['title'] or 'Untitled #' + str(doc['id']))}",
        f"matter: {_yaml_str(doc['matter'])}",
        "type: handwritten-note",
        "source: scribe",
        f"source_image: images/{doc['image_file']}",
        f"scanned_at: {_yaml_str(doc['created_at'])}",
        "status: approved",
        "---",
    ])

    abs_path = os.path.join(VAULT_DIR, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(front + "\n\n" + doc["transcript"].strip() + "\n")

    # If the title/matter changed since the last approval, the path moved.
    if doc["vault_file"] and doc["vault_file"] != rel_path:
        unpublish(doc["vault_file"])
    log(f"ingest | {doc['title'] or 'Untitled #' + str(doc['id'])} ({doc['matter'] or 'unfiled'})")
    return rel_path


def unpublish(rel_path):
    if not rel_path:
        return
    abs_path = os.path.join(VAULT_DIR, rel_path)
    try:
        os.remove(abs_path)
        os.rmdir(os.path.dirname(abs_path))  # remove matter dir if now empty
    except OSError:
        pass


def log(message):
    with open(os.path.join(VAULT_DIR, "log.md"), "a", encoding="utf-8") as f:
        f.write(f"## [{date.today().isoformat()}] {message}\n")


def rebuild_index():
    """Regenerate index.md from all approved documents (grouped by matter)."""
    init()
    lines = ["# Index", "",
             "Catalog of the firm knowledge vault. One line per document:",
             "`- path — title (date): summary`", ""]
    current_matter = None
    for doc in db.list_approved():
        matter = doc["matter"] or "Unfiled"
        if matter != current_matter:
            lines += [f"## {matter}", ""]
            current_matter = matter
        title = doc["title"] or f"Untitled #{doc['id']}"
        summary = " ".join(doc["summary"].split()) or " ".join(doc["transcript"].split()[:15])
        day = doc["created_at"][:10]
        lines.append(f"- {doc['vault_file']} — {title} ({day}): {summary}")
    lines.append("")
    with open(os.path.join(VAULT_DIR, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def read_index():
    try:
        with open(os.path.join(VAULT_DIR, "index.md"), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def read_file(rel_path):
    """Read a vault file, refusing paths that escape the vault."""
    abs_path = os.path.realpath(os.path.join(VAULT_DIR, rel_path))
    if not abs_path.startswith(os.path.realpath(VAULT_DIR) + os.sep):
        return None
    try:
        with open(abs_path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError):
        return None
