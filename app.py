import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import datetime
from html import unescape

import bleach
from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_from_directory, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("BASICWIKI_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "wiki.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
MAX_IMAGE_BYTES = 15 * 1024 * 1024

app = Flask(__name__)

ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u",
    "h1", "h2", "h3", "ul", "ol", "li",
    "a", "img", "pre", "code", "blockquote", "hr"
]


def allowed_image_attribute(tag, name, value):
    if name in ("alt", "title"):
        return True
    if name == "src":
        return bool(re.fullmatch(r"/uploads/[0-9a-f]{32}\.(?:jpg|png|gif|webp)", value))
    return False


ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": allowed_image_attribute,
}

IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

FILE_TYPES = {
    # Documents and common office formats (active web/executable formats omitted).
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
    "rtf": "application/rtf", "csv": "text/csv",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "epub": "application/epub+zip",
    # Audio.
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac",
    "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg",
    "oga": "audio/ogg", "opus": "audio/ogg",
    # Video.
    "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime",
    "webm": "video/webm", "ogv": "video/ogg", "avi": "video/x-msvideo",
    "mkv": "video/x-matroska", "mpeg": "video/mpeg", "mpg": "video/mpeg",
}

DEFAULT_SECTIONS = [
    ("home-assistant", "Home Assistant", "Automations, ESPHome, dashboards, devices, and troubleshooting."),
    ("docker", "Docker", "Containers, deployment notes, services, and maintenance."),
    ("networking", "Networking", "DNS, Wi-Fi, switches, routing, and infrastructure."),
    ("shop", "Shop", "Machining, 3D printing, electronics, laser work, and fabrication."),
    ("household", "Household", "House projects, repairs, appliances, maintenance, and reference notes."),
]


def get_db():
    if "db" not in g:
        os.makedirs(DATA_DIR, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content_html TEXT NOT NULL DEFAULT '',
            content_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(section_id) REFERENCES sections(id)
        );

        CREATE INDEX IF NOT EXISTS idx_pages_section_id ON pages(section_id);
        CREATE INDEX IF NOT EXISTS idx_pages_title ON pages(title);
    """)

    count = db.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    if count == 0:
        for sort_order, (slug, name, description) in enumerate(DEFAULT_SECTIONS, start=1):
            db.execute(
                "INSERT INTO sections (slug, name, description, sort_order) VALUES (?, ?, ?, ?)",
                (slug, name, description, sort_order),
            )
        db.commit()


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "page"


def unique_slug(title, page_id=None):
    base = slugify(title)
    slug = base
    n = 2
    db = get_db()
    while True:
        if page_id is None:
            row = db.execute("SELECT id FROM pages WHERE slug = ?", (slug,)).fetchone()
        else:
            row = db.execute("SELECT id FROM pages WHERE slug = ? AND id != ?", (slug, page_id)).fetchone()
        if row is None:
            return slug
        slug = f"{base}-{n}"
        n += 1


def sanitize_html(value):
    value = value or ""
    cleaned = bleach.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return bleach.linkify(cleaned)


def html_to_text(value):
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    value = re.sub(r"</(p|div|h1|h2|h3|li|pre|blockquote)>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


def detect_image_type(header):
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def safe_original_filename(value):
    value = unicodedata.normalize("NFC", value or "").strip()
    if (
        not value or value in (".", "..") or len(value) > 180
        or "/" in value or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        return None
    extension = value.rsplit(".", 1)[-1].lower() if "." in value else ""
    return value if extension in FILE_TYPES else None


@app.before_request
def ensure_db():
    init_db()


@app.route("/")
def home():
    db = get_db()
    sections = db.execute(
        """
        SELECT s.*,
               COUNT(p.id) AS page_count
        FROM sections s
        LEFT JOIN pages p ON p.section_id = s.id
        GROUP BY s.id
        ORDER BY s.sort_order, s.name
        """
    ).fetchall()

    recent = db.execute(
        """
        SELECT p.*, s.name AS section_name
        FROM pages p
        JOIN sections s ON s.id = p.section_id
        ORDER BY p.updated_at DESC
        LIMIT 8
        """
    ).fetchall()

    return render_template("home.html", sections=sections, recent=recent)


@app.route("/sections/new", methods=["GET", "POST"])
def new_section():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    error = None

    if request.method == "POST":
        if not name:
            error = "Section name is required."
        else:
            db = get_db()
            # Keep slug selection and ordering safe across simultaneous requests.
            with db:
                db.execute("BEGIN IMMEDIATE")
                base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "section"
                slug = base
                suffix = 2
                while db.execute(
                    "SELECT id FROM sections WHERE slug = ?", (slug,)
                ).fetchone() is not None:
                    slug = f"{base}-{suffix}"
                    suffix += 1

                sort_order = db.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM sections"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO sections (slug, name, description, sort_order) VALUES (?, ?, ?, ?)",
                    (slug, name, description, sort_order),
                )
            return redirect(url_for("section", slug=slug))

    return render_template(
        "new_section.html", name=name, description=description, error=error
    )


@app.route("/section/<slug>")
def section(slug):
    db = get_db()
    sec = db.execute("SELECT * FROM sections WHERE slug = ?", (slug,)).fetchone()
    if sec is None:
        abort(404)

    pages = db.execute(
        "SELECT * FROM pages WHERE section_id = ? ORDER BY title COLLATE NOCASE",
        (sec["id"],),
    ).fetchall()

    return render_template("section.html", section=sec, pages=pages)


@app.route("/page/<slug>")
def page(slug):
    db = get_db()
    row = db.execute(
        """
        SELECT p.*, s.name AS section_name, s.slug AS section_slug
        FROM pages p
        JOIN sections s ON s.id = p.section_id
        WHERE p.slug = ?
        """,
        (slug,),
    ).fetchone()
    if row is None:
        abort(404)
    return render_template("page.html", page=row)


@app.route("/page/new", methods=["GET", "POST"])
def new_page():
    db = get_db()
    sections = db.execute("SELECT * FROM sections ORDER BY sort_order, name").fetchall()
    selected_section = request.args.get("section", "")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        section_id = request.form.get("section_id", "").strip()
        content_html = sanitize_html(request.form.get("content_html", ""))

        if not title or not section_id:
            return render_template(
                "edit.html",
                page=None,
                sections=sections,
                selected_section=selected_section,
                error="Title and section are required.",
            )

        slug = unique_slug(title)
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            """
            INSERT INTO pages
                (section_id, slug, title, content_html, content_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (section_id, slug, title, content_html, html_to_text(content_html), now, now),
        )
        db.commit()
        return redirect(url_for("page", slug=slug))

    return render_template(
        "edit.html",
        page=None,
        sections=sections,
        selected_section=selected_section,
        error=None,
    )


@app.route("/page/<slug>/edit", methods=["GET", "POST"])
def edit_page(slug):
    db = get_db()
    row = db.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        abort(404)

    sections = db.execute("SELECT * FROM sections ORDER BY sort_order, name").fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        section_id = request.form.get("section_id", "").strip()
        content_html = sanitize_html(request.form.get("content_html", ""))

        if not title or not section_id:
            return render_template(
                "edit.html",
                page=row,
                sections=sections,
                selected_section="",
                error="Title and section are required.",
            )

        new_slug = unique_slug(title, page_id=row["id"])
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            """
            UPDATE pages
            SET section_id = ?, slug = ?, title = ?, content_html = ?,
                content_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                section_id,
                new_slug,
                title,
                content_html,
                html_to_text(content_html),
                now,
                row["id"],
            ),
        )
        db.commit()
        return redirect(url_for("page", slug=new_slug))

    return render_template(
        "edit.html",
        page=row,
        sections=sections,
        selected_section="",
        error=None,
    )


@app.post("/page/<slug>/delete")
def delete_page(slug):
    db = get_db()
    row = db.execute(
        """
        SELECT p.id, s.slug AS section_slug
        FROM pages p
        JOIN sections s ON s.id = p.section_id
        WHERE p.slug = ?
        """,
        (slug,),
    ).fetchone()
    if row is None:
        abort(404)

    db.execute("DELETE FROM pages WHERE id = ?", (row["id"],))
    db.commit()
    return redirect(url_for("section", slug=row["section_slug"]))


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        like = f"%{q}%"
        db = get_db()
        results = db.execute(
            """
            SELECT p.*, s.name AS section_name, s.slug AS section_slug
            FROM pages p
            JOIN sections s ON s.id = p.section_id
            WHERE p.title LIKE ? OR p.content_text LIKE ?
            ORDER BY
                CASE WHEN p.title LIKE ? THEN 0 ELSE 1 END,
                p.updated_at DESC
            """,
            (like, like, like),
        ).fetchall()
    return render_template("search.html", q=q, results=results)


@app.route("/api/pages")
def api_pages():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q:
        like = f"%{q}%"
        rows = db.execute(
            "SELECT title, slug FROM pages WHERE title LIKE ? ORDER BY title LIMIT 20",
            (like,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT title, slug FROM pages ORDER BY title LIMIT 50"
        ).fetchall()
    return jsonify([{"title": r["title"], "url": f"/page/{r['slug']}"} for r in rows])


@app.post("/api/uploads/images")
def upload_image():
    uploaded = request.files.get("image")
    if uploaded is None or not uploaded.filename:
        return jsonify(error="Choose an image to upload."), 400

    contents = uploaded.stream.read(MAX_IMAGE_BYTES + 1)
    if len(contents) > MAX_IMAGE_BYTES:
        return jsonify(error="Image is too large. The maximum size is 15 MB."), 413

    header = contents[:16]
    image_type = detect_image_type(header)
    if image_type is None:
        return jsonify(error="Only JPEG, PNG, GIF, and WEBP images are supported."), 415

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.{image_type}"
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as destination:
        destination.write(contents)

    return jsonify(
        url=url_for("uploaded_image", filename=filename),
        filename=uploaded.filename,
    ), 201


@app.get("/uploads/<filename>")
def uploaded_image(filename):
    image_match = re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|gif|webp)", filename)
    safe_file = safe_original_filename(filename)
    if not image_match and not safe_file:
        abort(404)

    extension = filename.rsplit(".", 1)[1].lower()
    response = send_from_directory(
        UPLOAD_DIR, filename, mimetype=(IMAGE_TYPES if image_match else FILE_TYPES)[extension],
        as_attachment=not image_match and extension != "pdf" and not FILE_TYPES[extension].startswith(("audio/", "video/")),
        download_name=filename, max_age=86400,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/api/uploads/files", methods=["GET", "POST"])
def uploaded_files():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    if request.method == "POST":
        uploaded = request.files.get("file")
        filename = safe_original_filename(uploaded.filename if uploaded else "")
        if filename is None:
            return jsonify(error="That file type is not supported or its filename is unsafe."), 415

        path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(path):
            return jsonify(error="A file with that name already exists."), 409
        uploaded.save(path)
        return jsonify(name=filename, url=url_for("uploaded_image", filename=filename)), 201

    files = []
    for filename in sorted(os.listdir(UPLOAD_DIR), key=str.casefold):
        if safe_original_filename(filename) and os.path.isfile(os.path.join(UPLOAD_DIR, filename)):
            files.append({"name": filename, "url": url_for("uploaded_image", filename=filename)})
    return jsonify(files)


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=8000, debug=False)
