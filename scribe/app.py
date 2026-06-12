"""Scribe: private handwriting capture, transcription, and search for a small office.

Run on a PC on the office network; open it from a phone's browser to snap
photos of handwritten pages. Images, transcripts, and the search index are
all stored locally (SQLite + files on disk). OCR runs on a local model via
Ollama — nothing is sent to any cloud service.
"""
import io
import os
import queue
import secrets
import threading
import time

from flask import (
    Flask, abort, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from markupsafe import Markup, escape
from PIL import Image, ImageOps

import db
import ocr
import vault

try:  # iPhones may upload HEIC images from the photo library
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MAX_IMAGE_DIM = 2048  # downscale uploads; plenty for OCR, keeps the model fast

app = Flask(__name__)
app.secret_key = os.environ.get("SCRIBE_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

PASSWORD = os.environ.get("SCRIBE_PASSWORD", "")

work_queue: "queue.Queue[int]" = queue.Queue()


# ---------------------------------------------------------------- auth

@app.before_request
def require_login():
    if not PASSWORD or request.endpoint in ("login", "static"):
        return None
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), PASSWORD):
            session["authed"] = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "Wrong password"
    return render_template("login.html", error=error)


# ---------------------------------------------------------------- pages

@app.route("/")
def index():
    return render_template("index.html", docs=db.list_documents(),
                           engine=ocr.OCR_ENGINE, model=ocr.OLLAMA_MODEL)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("photo")
    if not file or not file.filename:
        abort(400, "No photo uploaded")
    image = Image.open(io.BytesIO(file.read()))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))

    name = f"{int(time.time())}_{secrets.token_hex(4)}.jpg"
    image.save(os.path.join(db.IMAGES_DIR, name), "JPEG", quality=90)

    doc_id = db.create_document(
        name,
        title=request.form.get("title", "").strip(),
        matter=request.form.get("matter", "").strip(),
    )
    if ocr.OCR_ENGINE == "none":
        db.update_document(doc_id, status="done")
    else:
        work_queue.put(doc_id)
    return redirect(url_for("document", doc_id=doc_id))


@app.route("/doc/<int:doc_id>")
def document(doc_id):
    doc = db.get_document(doc_id) or abort(404)
    return render_template("document.html", doc=doc)


@app.route("/doc/<int:doc_id>/save", methods=["POST"])
def save(doc_id):
    db.get_document(doc_id) or abort(404)
    db.update_document(
        doc_id,
        title=request.form.get("title", "").strip(),
        matter=request.form.get("matter", "").strip(),
        transcript=request.form.get("transcript", ""),
        status="done",
        error="",
    )
    return redirect(url_for("document", doc_id=doc_id))


@app.route("/doc/<int:doc_id>/approve", methods=["POST"])
def approve(doc_id):
    """Save edits, then publish the transcript to the knowledge vault."""
    doc = db.get_document(doc_id) or abort(404)
    db.update_document(
        doc_id,
        title=request.form.get("title", "").strip(),
        matter=request.form.get("matter", "").strip(),
        transcript=request.form.get("transcript", ""),
        error="",
    )
    rel_path = vault.publish(db.get_document(doc_id))
    db.update_document(doc_id, status="approved", vault_file=rel_path)
    return redirect(url_for("document", doc_id=doc_id))


@app.route("/doc/<int:doc_id>/retranscribe", methods=["POST"])
def retranscribe(doc_id):
    db.get_document(doc_id) or abort(404)
    db.update_document(doc_id, status="pending", error="")
    work_queue.put(doc_id)
    return redirect(url_for("document", doc_id=doc_id))


@app.route("/doc/<int:doc_id>/delete", methods=["POST"])
def delete(doc_id):
    doc = db.get_document(doc_id) or abort(404)
    db.delete_document(doc_id)
    vault.unpublish(doc["vault_file"])
    try:
        os.remove(os.path.join(db.IMAGES_DIR, doc["image_file"]))
    except OSError:
        pass
    return redirect(url_for("index"))


@app.route("/doc/<int:doc_id>/status")
def status(doc_id):
    doc = db.get_document(doc_id) or abort(404)
    return jsonify(status=doc["status"], error=doc["error"])


@app.route("/image/<int:doc_id>")
def image(doc_id):
    doc = db.get_document(doc_id) or abort(404)
    return send_from_directory(db.IMAGES_DIR, doc["image_file"])


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    results = []
    for row in (db.search(q) if q else []):
        doc = dict(row)
        # Escape transcript text first, then turn the FTS5 highlight markers
        # (\x02/\x03, set in db.search) into <mark> tags.
        snip = str(escape(doc["snip"])).replace("\x02", "<mark>").replace("\x03", "</mark>")
        doc["snip"] = Markup(snip)
        results.append(doc)
    return render_template("search.html", q=q, results=results)


# ---------------------------------------------------------------- OCR worker

def worker():
    while True:
        doc_id = work_queue.get()
        doc = db.get_document(doc_id)
        if doc is None or doc["status"] not in ("pending", "processing"):
            continue
        db.update_document(doc_id, status="processing")
        try:
            text = ocr.transcribe(os.path.join(db.IMAGES_DIR, doc["image_file"]))
            db.update_document(doc_id, transcript=text, status="done", error="")
        except Exception as e:  # noqa: BLE001 - record failure, keep worker alive
            db.update_document(doc_id, status="error", error=str(e))


def start_worker():
    threading.Thread(target=worker, daemon=True).start()
    for doc_id in db.pending_ids():  # resume jobs interrupted by a restart
        work_queue.put(doc_id)


db.init()
start_worker()


if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("SCRIBE_PORT", "8000"))
    print(f"Scribe listening on http://0.0.0.0:{port} (open from your phone on the same Wi-Fi)")
    serve(app, host="0.0.0.0", port=port, threads=8)
