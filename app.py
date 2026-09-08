import os
import re
import sqlite3
from datetime import datetime
from html import unescape

import bleach
from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("BASICWIKI_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "wiki.db")

app = Flask(__name__)

ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u",
    "h1", "h2", "h3", "ul", "ol", "li",
    "a", "pre", "code", "blockquote", "hr"
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"]
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


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=8000, debug=False)
