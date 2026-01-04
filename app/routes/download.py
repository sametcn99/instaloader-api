"""API routes for Instagram downloads."""

import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.models import (
    DownloadRequest,
    DownloadStats,
    ContentType,
    ProfileInfo,
    ErrorResponse,
    SuccessResponse,
)
from app.exceptions import InstagramDownloaderError
from app.services.insta_service import get_insta_service
from app.utils.zip_utils import (
    create_zip_archive,
    create_temp_download_dir,
    cleanup_directory,
    count_files_in_directory,
    get_zip_size,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def schedule_cleanup(path: Path, delay_seconds: int = 300) -> None:
    """Schedule cleanup of a path after a delay."""
    import threading
    
    def cleanup():
        time.sleep(delay_seconds)
        cleanup_directory(path)
        # Also clean up the zip file if it exists
        zip_path = path.parent / f"{path.name}.zip"
        if zip_path.exists():
            zip_path.unlink()
    
    if settings.AUTO_CLEANUP:
        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()


@router.get(
    "/profile/{username}",
    response_model=ProfileInfo,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get Profile Information",
    description="Returns basic profile information for an Instagram user."
)
async def get_profile(username: str):
    """Get profile information for a user."""
    try:
        service = get_insta_service()
        return service.get_profile_info(username)
    except InstagramDownloaderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.exception("Unexpected error getting profile")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/download/all/{username}",
    responses={
        200: {"content": {"application/zip": {}}, "description": "ZIP file"},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Download All Content",
    description="Downloads profile picture, posts, and stories in a single ZIP file."
)
async def download_all(
    username: str,
    background_tasks: BackgroundTasks,
    max_posts: Annotated[int | None, Query(ge=1, le=1000, description="Maximum number of posts")] = None,
    include_metadata: Annotated[bool, Query(description="Include metadata files")] = True,
):
    """Download all content from a profile."""
    start_time = time.time()
    temp_dir = None
    
    try:
        service = get_insta_service()
        temp_dir = create_temp_download_dir(username)
        
        # Download everything
        stats = service.download_all(
            username=username,
            target_dir=temp_dir,
            max_posts=max_posts,
            include_metadata=include_metadata
        )
        
        # Create ZIP
        zip_path = create_zip_archive(temp_dir, username, temp_dir.parent)
        
        # Schedule cleanup
        schedule_cleanup(temp_dir, settings.CLEANUP_AFTER_SECONDS)
        
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=f"{username}.zip",
            headers={
                "X-Download-Stats-Posts": str(stats["posts"]),
                "X-Download-Stats-Stories": str(stats["stories"]),
                "X-Download-Stats-ProfilePic": str(stats["profile_pic"]),
                "X-Download-Time-Seconds": f"{time.time() - start_time:.2f}",
            }
        )
        
    except InstagramDownloaderError as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        logger.exception("Unexpected error during download")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/download/posts/{username}",
    responses={
        200: {"content": {"application/zip": {}}, "description": "ZIP file"},
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Download Posts",
    description="Downloads all user posts (photos/videos)."
)
async def download_posts(
    username: str,
    background_tasks: BackgroundTasks,
    max_posts: Annotated[int | None, Query(ge=1, le=1000, description="Maximum number of posts")] = None,
    include_metadata: Annotated[bool, Query(description="Include metadata files")] = True,
):
    """Download only posts from a profile."""
    start_time = time.time()
    temp_dir = None
    
    try:
        service = get_insta_service()
        temp_dir = create_temp_download_dir(username)
        
        # Download posts
        posts = service.download_posts(
            username=username,
            target_dir=temp_dir / "posts",
            max_posts=max_posts,
            include_metadata=include_metadata
        )
        
        if not posts:
            cleanup_directory(temp_dir)
            raise HTTPException(status_code=404, detail="No posts found to download.")
        
        # Create ZIP
        zip_path = create_zip_archive(temp_dir, f"{username}_posts", temp_dir.parent)
        
        # Schedule cleanup
        schedule_cleanup(temp_dir, settings.CLEANUP_AFTER_SECONDS)
        
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=f"{username}_posts.zip",
            headers={
                "X-Download-Stats-Posts": str(len(posts)),
                "X-Download-Time-Seconds": f"{time.time() - start_time:.2f}",
            }
        )
        
    except InstagramDownloaderError as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        logger.exception("Unexpected error during posts download")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/download/stories/{username}",
    responses={
        200: {"content": {"application/zip": {}}, "description": "ZIP file"},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Download Stories",
    description="Downloads user's current stories. You must be logged in to use this feature."
)
async def download_stories(
    username: str,
    background_tasks: BackgroundTasks,
):
    """Download stories from a profile."""
    start_time = time.time()
    temp_dir = None
    
    try:
        service = get_insta_service()
        temp_dir = create_temp_download_dir(username)
        
        # Download stories
        story_count = service.download_stories(
            username=username,
            target_dir=temp_dir / "stories"
        )
        
        if story_count == 0:
            cleanup_directory(temp_dir)
            raise HTTPException(status_code=404, detail="No active stories found for this user.")
        
        # Create ZIP
        zip_path = create_zip_archive(temp_dir, f"{username}_stories", temp_dir.parent)
        
        # Schedule cleanup
        schedule_cleanup(temp_dir, settings.CLEANUP_AFTER_SECONDS)
        
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=f"{username}_stories.zip",
            headers={
                "X-Download-Stats-Stories": str(story_count),
                "X-Download-Time-Seconds": f"{time.time() - start_time:.2f}",
            }
        )
        
    except InstagramDownloaderError as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        logger.exception("Unexpected error during stories download")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/download/profile-pic/{username}",
    responses={
        200: {"content": {"image/jpeg": {}, "application/json": {}}, "description": "Profile picture or URL"},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Download Profile Picture",
    description="Downloads user's profile picture. Works for private profiles as well."
)
async def download_profile_pic(
    username: str,
    background_tasks: BackgroundTasks,
    url_only: Annotated[bool, Query(description="Return only the image URL instead of downloading")] = False,
):
    """Download profile picture."""
    start_time = time.time()
    temp_dir = None
    
    try:
        service = get_insta_service()
        
        # If url_only, just return the profile pic URL
        if url_only:
            profile_info = service.get_profile_info(username)
            return JSONResponse(content={
                "username": username,
                "profile_pic_url": profile_info.profile_pic_url,
            })
        
        temp_dir = create_temp_download_dir(username)
        
        # Download profile pic
        pic_path = service.download_profile_pic(
            username=username,
            target_dir=temp_dir
        )
        
        if not pic_path or not pic_path.exists():
            cleanup_directory(temp_dir)
            raise HTTPException(status_code=404, detail="Failed to download profile picture.")
        
        # Determine media type based on file extension
        ext = pic_path.suffix.lower()
        media_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp'
        }
        media_type = media_types.get(ext, 'image/jpeg')
        
        # Schedule cleanup
        schedule_cleanup(temp_dir, settings.CLEANUP_AFTER_SECONDS)
        
        return FileResponse(
            path=pic_path,
            media_type=media_type,
            filename=f"{username}_profile_pic{ext}",
            headers={
                "X-Download-Time-Seconds": f"{time.time() - start_time:.2f}",
            }
        )
        
    except InstagramDownloaderError as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        if temp_dir:
            cleanup_directory(temp_dir)
        logger.exception("Unexpected error during profile pic download")
        raise HTTPException(status_code=500, detail=str(e))
