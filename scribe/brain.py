"""'Ask the firm' — agentic retrieval over the vault, per Karpathy's LLM-wiki
pattern: the model reads index.md, picks the relevant files, reads only
those, and answers with citations. No embeddings, no vector DB; everything
runs on the local Ollama model.
"""
import os
import re

import requests

import ocr
import vault

MAX_FILES = int(os.environ.get("ASK_MAX_FILES", "6"))
MAX_FILE_CHARS = 8000
SUMMARY_TIMEOUT = int(os.environ.get("SUMMARY_TIMEOUT", "120"))

SELECT_PROMPT = """You are the retrieval step of a law firm's private knowledge assistant.
Below is the index of the firm's knowledge vault, then a question.

List the paths of the documents most likely to answer the question, one path
per line, exactly as written in the index, most relevant first, at most {max_files}.
If nothing in the index is relevant, output exactly: NONE
Output only paths (or NONE), nothing else.

=== INDEX ===
{index}

=== QUESTION ===
{question}
"""

ANSWER_PROMPT = """You are a private knowledge assistant for a small law firm.
Answer the question using ONLY the documents below. Rules:
- Cite the file path of every document you rely on.
- If the documents do not contain the answer, say so plainly.
- Answer in the same language as the question.
- Be concise and factual; quote exact wording when the precise phrasing matters.

{documents}

=== QUESTION ===
{question}
"""


class BrainError(Exception):
    pass


def _generate(prompt, timeout=None):
    try:
        resp = requests.post(
            f"{ocr.OLLAMA_URL}/api/generate",
            json={"model": ocr.OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0}},
            timeout=timeout or ocr.OLLAMA_TIMEOUT,
        )
    except requests.ConnectionError as e:
        raise BrainError(f"Cannot reach Ollama at {ocr.OLLAMA_URL}. Is it running?") from e
    except requests.Timeout as e:
        raise BrainError("The local model timed out.") from e
    if not resp.ok:
        raise BrainError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("response", "").strip()


def summarize(text):
    """One-line summary for index.md. Best effort: empty string on failure."""
    if ocr.OCR_ENGINE == "none":
        return ""
    try:
        out = _generate(
            "Summarize the following note in ONE short line (max 15 words), in the "
            "note's own language. Output only the summary line.\n\n" + text[:MAX_FILE_CHARS],
            timeout=SUMMARY_TIMEOUT,
        )
        return " ".join(out.split())[:200]
    except BrainError:
        return ""


def ask(question):
    """Returns (answer, [vault paths consulted])."""
    index = vault.read_index()
    if not index.strip() or "- raw/" not in index.replace("\\", "/"):
        raise BrainError("The knowledge vault is empty — approve some documents first.")

    selection = _generate(SELECT_PROMPT.format(
        max_files=MAX_FILES, index=index, question=question))
    if selection.strip().upper() == "NONE":
        return ("Nothing in the firm's knowledge vault appears relevant to this question.", [])

    paths, docs = [], []
    for line in selection.splitlines():
        # tolerate models echoing the index bullet format around the path
        m = re.search(r"(raw/\S+\.md|wiki/\S+\.md)", line.replace("\\", "/"))
        if not m or m.group(1) in paths:
            continue
        content = vault.read_file(m.group(1))
        if content is None:
            continue
        paths.append(m.group(1))
        docs.append(f"=== DOCUMENT: {m.group(1)} ===\n{content[:MAX_FILE_CHARS]}")
        if len(paths) >= MAX_FILES:
            break
    if not docs:
        return ("The model could not identify any relevant documents in the vault "
                "for this question.", [])

    answer = _generate(ANSWER_PROMPT.format(documents="\n\n".join(docs), question=question))
    return (answer, paths)
