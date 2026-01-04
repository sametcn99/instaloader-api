"""ZIP file creation utilities."""

import os
import shutil
import zipfile
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def create_zip_archive(
    source_dir: Path,
    zip_name: str,
    output_dir: Path | None = None
) -> Path:
    """
    Create a ZIP archive from a directory.
    
    Args:
        source_dir: Directory to compress
        zip_name: Name of the ZIP file (without extension)
        output_dir: Where to save the ZIP (defaults to source_dir parent)
        
    Returns:
        Path to the created ZIP file
    """
    if output_dir is None:
        output_dir = source_dir.parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{zip_name}.zip"
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(source_dir)
                zipf.write(file_path, arcname)
    
    return zip_path


def get_zip_size(zip_path: Path) -> int:
    """Get the size of a ZIP file in bytes."""
    return zip_path.stat().st_size if zip_path.exists() else 0


def count_files_in_directory(directory: Path) -> int:
    """Count all files in a directory recursively."""
    if not directory.exists():
        return 0
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def cleanup_directory(directory: Path) -> None:
    """Remove a directory and all its contents."""
    if directory.exists():
        shutil.rmtree(directory)
        logger.debug(f"Cleaned up directory: {directory}")


def create_temp_download_dir(username: str) -> Path:
    """
    Create a temporary directory for downloads.
    
    Args:
        username: Instagram username
        
    Returns:
        Path to the temporary directory
    """
    from app.config import settings
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_dir = settings.DOWNLOAD_DIR / f"{username}_{timestamp}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    return temp_dir
