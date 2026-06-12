"""SQLite storage with FTS5 full-text search. Everything stays on local disk."""
import os
import sqlite3

DATA_DIR = os.environ.get("SCRIBE_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "scribe.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    matter      TEXT NOT NULL DEFAULT '',
    image_file  TEXT NOT NULL,
    transcript  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT NOT NULL DEFAULT '',
    vault_file  TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, matter, transcript,
    content='documents', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, matter, transcript)
    VALUES (new.id, new.title, new.matter, new.transcript);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, matter, transcript)
    VALUES ('delete', old.id, old.title, old.matter, old.transcript);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, matter, transcript)
    VALUES ('delete', old.id, old.title, old.matter, old.transcript);
    INSERT INTO documents_fts(rowid, title, matter, transcript)
    VALUES (new.id, new.title, new.matter, new.transcript);
END;
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)")]
        for col in ("vault_file", "summary"):
            if col not in cols:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")


def create_document(image_file, title="", matter=""):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO documents (image_file, title, matter) VALUES (?, ?, ?)",
            (image_file, title, matter),
        )
        return cur.lastrowid


def get_document(doc_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()


def list_documents(limit=50):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM documents ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def list_approved():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE status = 'approved' ORDER BY matter, created_at"
        ).fetchall()


def update_document(doc_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE documents SET {cols} WHERE id = ?", (*fields.values(), doc_id))


def delete_document(doc_id):
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def pending_ids():
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM documents WHERE status IN ('pending', 'processing') ORDER BY id"
        ).fetchall()
        return [r["id"] for r in rows]


def search(query, limit=50):
    """FTS5 search across title, matter, and transcript with snippets."""
    # Quote each term so user input (hyphens, apostrophes) can't break FTS syntax.
    terms = [t.replace('"', '""') for t in query.split()]
    match = " ".join(f'"{t}"*' for t in terms)
    if not match:
        return []
    with connect() as conn:
        return conn.execute(
            """
            SELECT d.*, snippet(documents_fts, 2, char(2), char(3), ' … ', 16) AS snip
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
