FROM python:3.11-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY app/ ./app/

# Install dependencies
RUN pip install --no-cache-dir .

# Create download directory
RUN mkdir -p /tmp/insta_downloads

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
