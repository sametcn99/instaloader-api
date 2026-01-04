"""Application configuration settings."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    # App settings
    APP_NAME: str = "Instagram Downloader API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Download settings
    DOWNLOAD_DIR: Path = Path("/tmp/insta_downloads")
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 300  # seconds
    
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
