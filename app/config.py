"""Application configuration settings."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    # App settings
    APP_NAME: str = "Instaloader API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Download settings
    DOWNLOAD_DIR: Path = Path("/tmp/insta_downloads")
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 300  # seconds

    # Instagram auth/headers (optional)
    IG_SESSIONID: str | None = None
    IG_USER_AGENT: str | None = None

    # Proxy settings (rotate for throttling mitigation)
    PROXIES: list[str] = []  # e.g. ["http://user:pass@host:port", "http://host2:port"]
    PROXY_ROTATION: bool = True
    PROXY_RETRY_MAX: int = 4
    PROXY_BACKOFF_BASE: float = 1.5  # seconds
    PROXY_BACKOFF_JITTER: float = 0.5  # seconds
    
    # Rate limiting
    RATE_LIMIT_REQUESTS: int = 10
    RATE_LIMIT_PERIOD: int = 60  # seconds
    
    # Cleanup settings
    AUTO_CLEANUP: bool = True
    CLEANUP_AFTER_SECONDS: int = 300  # 5 minutes
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Ensure download directory exists
settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
