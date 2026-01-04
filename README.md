# Instaloader API

A FastAPI-based wrapper around [Instaloader](https://github.com/instaloader/instaloader) that downloads Instagram profile content (posts, and profile pictures) and serves it as ZIP archives. Includes optional authentication, simple rate handling, and automatic cleanup of temporary downloads.

## Features

- Download profile posts, and profile pictures as ZIPs
- Download single posts by link/shortcode (returns raw file if one item, ZIP if carousel)
- Profile info lookup with follower counts and verification flag
- Metadata export for posts (caption, hashtags, likes, comments, location)
- Temp download isolation per request with scheduled cleanup
- Configurable limits for posts and request frequency
- Ready-to-run Docker image and CLI entrypoint (`insta-save`)

## Requirements

- Python 3.11+
- `instaloader` download prerequisites (network access to Instagram)

## Quick Start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The interactive docs are served at `/` (Swagger) and `/redoc` (ReDoc).

## Configuration

Set environment variables or a `.env` file (loaded automatically). Key options:

| Name                       | Default              | Description                                     |
|----------------------------|----------------------|-------------------------------------------------|
| `APP_NAME`                 | Instaloader API      | API title used in docs                          |
| `APP_VERSION`              | 1.0.0                | Version string                                  |
| `DEBUG`                    | false                | Enables debug logging and auto-reload           |
| `DOWNLOAD_DIR`             | /tmp/insta_downloads | Base directory for temp downloads               |
| `MAX_CONCURRENT_DOWNLOADS` | 3                    | Reserved for future concurrency control         |
| `DOWNLOAD_TIMEOUT`         | 300                  | Seconds before download timeout (service level) |
| `INSTAGRAM_USERNAME`       | None                 | Instagram username for login                    |
| `INSTAGRAM_PASSWORD`       | None                 | Instagram password for login                    |
| `INSTAGRAM_SESSION_FILE`   | None                 | Path to saved Instaloader session file          |
| `RATE_LIMIT_REQUESTS`      | 10                   | Requests allowed per period                     |
| `RATE_LIMIT_PERIOD`        | 60                   | Rate limit window in seconds                    |
| `AUTO_CLEANUP`             | true                 | Enable background cleanup of temp folders       |
| `CLEANUP_AFTER_SECONDS`    | 300                  | Delay before temp folders are removed           |

Example `.env`:

```env
DEBUG=true
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
# or use a session file instead of credentials
INSTAGRAM_SESSION_FILE=/path/to/session
```

## Running with Docker

```bash
docker build -t instaloader-api .
docker run -p 8000:8000 \
  -e DEBUG=true \
  -e INSTAGRAM_SESSION_FILE=/sessions/sessionfile \
  -v $(pwd)/sessions:/sessions \
  -v $(pwd)/downloads:/tmp/insta_downloads \
  instaloader-api
```

Mounting `/tmp/insta_downloads` is optional but keeps ZIPs accessible outside the container until cleanup runs.

## API Endpoints

Base URL: `http://localhost:8000`

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| GET | `/profile/{username}` | Profile info (public; private requires login) |
| GET | `/download/all/{username}` | Download profile pic, posts as one ZIP |
| GET | `/download/posts/{username}` | Download posts only (ZIP) |
| GET | `/download/profile-pic/{username}` | Download profile picture or return URL |
| GET | `/download/post` | Download a single post by link/shortcode (file or ZIP) |

Common query parameters:

- `max_posts` (int, 1-1000): Limit number of posts (where supported)
- `include_metadata` (bool): Save `metadata.txt` per post (default `true`)
- `url_only` (bool): For profile picture endpoint, return the image URL instead of a file

## Usage Examples

Health check:

```bash
curl http://localhost:8000/health
```

Profile info:

```bash
curl http://localhost:8000/profile/instagram
```

Download everything:

```bash
curl -L -o instagram.zip \
  "http://localhost:8000/download/all/instagram?max_posts=50&include_metadata=true"
```

Download posts only:

```bash
curl -L -o instagram_posts.zip \
  "http://localhost:8000/download/posts/instagram?max_posts=25"
```

Download profile picture file:

```bash
curl -L -o profile.jpg \
  "http://localhost:8000/download/profile-pic/instagram"
```

Profile picture URL only:

```bash
curl "http://localhost:8000/download/profile-pic/instagram?url_only=true"
```

Download a single post by link (returns file if one media, ZIP if multiple):

```bash
curl -L -o post.bin \
  "http://localhost:8000/download/post?url=https://www.instagram.com/p/POSTCODE/"
```

Add `include_metadata=false` to skip `metadata.txt` inside ZIPs.
```

## Responses and Headers

- Download endpoints return ZIP files (or images for profile pictures). Numeric stats are exposed via `X-Download-Stats-*` and `X-Download-Time-Seconds` headers when available.
- Errors follow `ErrorResponse` with fields `success`, `error`, `error_code`, and `timestamp`.

## Authentication Notes

- Public data (public profiles, public posts) may work without login. Private profiles, and rate-limit avoidance require either credentials or a session file.
- For session files, use Instaloader locally: `instaloader --login YOUR_USER --sessionfile session`.

## Cleanup Behavior

- Each request writes to a unique subfolder under `DOWNLOAD_DIR`.
- When `AUTO_CLEANUP` is true, folders and generated ZIPs are deleted after `CLEANUP_AFTER_SECONDS` via a background thread.

## Project Layout

- `app/main.py` FastAPI app and exception handlers
- `app/routes/download.py` HTTP routes
- `app/services/insta_service.py` Instaloader integration and business logic
- `app/utils/zip_utils.py` ZIP helpers and temp dir management
- `app/models.py` Pydantic request/response schemas
- `Dockerfile` Container build
- `pyproject.toml` Project metadata and dependencies

## Development and Testing

Install dev deps and run tests:

```bash
pip install -e .[dev]
pytest
```

## Troubleshooting

- **429 / rate limited**: Provide login credentials or session; reduce request frequency.
- **Private profiles**: Require authenticated session that follows the target account.
- **Downloads empty**: Check `max_posts` and that the profile actually has posts.
