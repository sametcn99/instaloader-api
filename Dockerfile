FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Create non-root user and writable temp dir
RUN adduser --disabled-password --gecos "" appuser \
	&& mkdir -p /tmp/insta_downloads \
	&& chown -R appuser:appuser /app /tmp/insta_downloads

# Copy project files
COPY pyproject.toml README.md ./
COPY app/ ./app/

# Install dependencies with cached wheels between builds
RUN --mount=type=cache,target=/root/.cache/pip \
	python -m pip install --no-cache-dir --upgrade pip \
	&& python -m pip install --no-cache-dir .

EXPOSE 8000

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
