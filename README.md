# Instaloader API

A FastAPI-based wrapper around [Instaloader](https://github.com/instaloader/instaloader) and [Instagrapi](https://github.com/subzeroid/instagrapi) that downloads Instagram profile content (posts, and profile pictures) and serves it as ZIP archives. Includes optional authentication, simple rate handling, and automatic cleanup of temporary downloads.

## Features

- Download profile posts, and profile pictures as ZIPs
- Download single posts by link/shortcode (returns raw file if one item, ZIP if carousel)
- Profile info lookup with follower counts and verification flag
- Metadata export for posts (caption, hashtags, likes, comments, location)
- Temp download isolation per request with scheduled cleanup
- Configurable limits for posts and request frequency

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
