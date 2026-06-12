"""Knowledge vault: approved transcripts published as Markdown + YAML frontmatter.

The vault is a plain folder of .md files organized by matter — the firm's
canonical, tool-agnostic knowledge store. It can be browsed with Obsidian,
synced to the office file server, and indexed by any local search/RAG tool.
Scribe is one ingestion source; emails, filings, etc. can feed the same vault
later using the same frontmatter convention.
"""
import os
import re

import db

VAULT_DIR = os.environ.get("SCRIBE_VAULT_DIR", os.path.join(db.DATA_DIR, "vault"))


def _slug(text, fallback):
    """Filesystem-safe name that keeps Unicode (e.g. Hebrew) letters."""
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", "-", text)
    return text[:80] or fallback


def _yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def publish(doc):
    """Write the document to the vault; returns the path relative to VAULT_DIR."""
    matter_dir = _slug(doc["matter"], "_unfiled")
    name = f"{_slug(doc['title'], 'note')}-{doc['id']}.md"
    rel_path = os.path.join(matter_dir, name)

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
