"""Handwriting transcription backends. All processing happens on the local machine.

Engines (set OCR_ENGINE):
  ollama  (default) - sends the image to a locally running Ollama vision model
                      such as qwen2.5vl. Nothing leaves the machine/LAN.
  none              - no automatic OCR; transcripts are typed in by hand.
"""
import base64
import os

import requests

OCR_ENGINE = os.environ.get("OCR_ENGINE", "ollama")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-vl:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))

PROMPT = (
    "Transcribe ALL text in this image, including handwriting. "
    "Reproduce it exactly as written, preserving line breaks and original "
    "spelling. If a word is illegible, write [illegible]. "
    "Output only the transcription, with no commentary."
)


class OcrError(Exception):
    pass


def transcribe(image_path: str) -> str:
    if OCR_ENGINE == "none":
        raise OcrError("Automatic OCR is disabled (OCR_ENGINE=none); type the transcript manually.")
    if OCR_ENGINE == "ollama":
        return _ollama(image_path)
    raise OcrError(f"Unknown OCR_ENGINE: {OCR_ENGINE!r}")


def _ollama(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": PROMPT,
                "images": [image_b64],
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=OLLAMA_TIMEOUT,
        )
    except requests.ConnectionError as e:
        raise OcrError(
            f"Cannot reach Ollama at {OLLAMA_URL}. Is it running? "
            f"(install from https://ollama.com, then: ollama pull {OLLAMA_MODEL})"
        ) from e
    except requests.Timeout as e:
        raise OcrError(f"Ollama timed out after {OLLAMA_TIMEOUT}s") from e
    if resp.status_code == 404:
        raise OcrError(
            f"Model {OLLAMA_MODEL!r} not found in Ollama. Run: ollama pull {OLLAMA_MODEL}"
        )
    if not resp.ok:
        raise OcrError(f"Ollama error {resp.status_code}: {resp.text[:500]}")
    text = resp.json().get("response", "").strip()
    if not text:
        raise OcrError("Ollama returned an empty transcription")
    return text
