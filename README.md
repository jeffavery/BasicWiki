![Project Header Banner](images/header.png)
# BasicWiki

BasicWiki is a deliberately small, self-hosted personal knowledge base for home-lab, shop, household, and technical notes.

It is designed for people who want simple web pages and a basic WYSIWYG editor without learning wiki markup or running a large database stack.

## Features

- Five built-in sections:
  - Home Assistant
  - Docker
  - Networking
  - Shop
  - Household
- Simple WYSIWYG-style editor
- Bold, italic, headings, bullet lists, links, internal wiki links, and code blocks
- Full-text search across page titles and page content
- SQLite storage
- Docker deployment
- No MySQL or PostgreSQL
- No external JavaScript or CSS dependencies
- Easy backup and restore

## Data and privacy

The application code can safely live in GitHub.

Actual wiki content is stored in:

```text
./data/wiki.db
```

The `data/` directory and `*.db` files are excluded by `.gitignore`, so your notes are not committed to GitHub.

## Docker deployment

```bash
git clone https://github.com/jeffavery/BasicWiki.git
cd BasicWiki
mkdir -p data
docker compose up -d --build
```

BasicWiki will listen on:

```text
http://localhost:8085
```

The default Docker Compose mapping is intentionally `8085:8000`, allowing it to replace a previous service already proxied to host port 8085.

## Backup

Stop the container for the cleanest possible file-level copy:

```bash
docker compose stop
cp data/wiki.db /path/to/backup/wiki.db
docker compose start
```

For a small personal installation, copying the SQLite database is all that is required to preserve the wiki content.

## Restore

```bash
docker compose down
cp /path/to/backup/wiki.db data/wiki.db
docker compose up -d
```

## Updating

Because the wiki content lives under `data/` and is ignored by Git, application updates do not overwrite your notes.

```bash
git pull
docker compose up -d --build
```

## Architecture

- Python / Flask
- SQLite
- Gunicorn
- Plain HTML, CSS, and JavaScript
- `contenteditable` browser editor with a small formatting toolbar

BasicWiki is intentionally small and straightforward.
