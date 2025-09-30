# MBOX → CSV Converter

This project powers **mbox-csv.com**, a FastAPI application that converts large email archives from the MBOX format into downloadable CSV files.

## Features

- Resumable, checksum-verified uploads that support archives up to 20 GB.
- Background parsing that streams headers and recipients to `emails.csv` while trimming plain-text bodies to 32K characters.
- Automatic inclusion of the email body column—no UI toggles required.
- Optional attachments manifest available through the API for power users.
- Static marketing pages and preview assets served directly from FastAPI.

## Repository layout

```
app/
  main.py          # FastAPI application (API, HTML, and background worker)
  pages/           # Stand-alone HTML pages (FAQ, privacy, terms, etc.)
  static/          # Static assets referenced by the UI (CSS, SVG, icons)
public/             # Placeholder for deployment-specific assets (if needed)
docker-compose.yml # Convenience entry point for running via Docker
```

The application expects writable directories at `/data` (for uploads and job metadata) and `/downloads` (for finished ZIP archives). Both locations are created automatically on startup. When using Docker the bind mounts in `docker-compose.yml` map them to the local `data/` and `downloads/` folders.

## Running locally

### With Python

1. Install dependencies:
   ```bash
   pip install fastapi uvicorn[standard] python-multipart
   ```
2. Start the app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
3. Visit `http://localhost:8000/` in a browser.

### With Docker Compose

```bash
docker-compose up
```

This builds a container using the official `python:3.11-slim` image, installs runtime dependencies, and exposes the service on `http://localhost:8000/`.

## Development notes

- Uploaded chunks are written to `/data/uploads` and verified with SHA-256 hashes before being moved into the parsing queue.
- Parsed results are stored as `emails.zip` inside `/downloads`, containing an `emails.csv` file with `date`, `from`, `to`, `cc`, `bcc`, `subject`, `message_id`, and the plain-text `body` column.
- The optional attachments manifest can be enabled programmatically by posting `{"include_attachments": true}` in the `/upload/init` payload.
- Front-end assets live alongside the API in `app/main.py` to simplify deployment to serverless or container platforms.

