"""API routes for Instagram downloads."""

import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import requests

from app.config import settings
from app.models import (
    DownloadRequest,
    DownloadStats,
    ContentType,
    ProfileInfo,
    ErrorResponse,
    SuccessResponse,
    PostListResponse,
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
    "/proxy/thumbnail",
    responses={502: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Proxy Instagram thumbnail",
    description="Fetches an Instagram CDN image via the backend to avoid client-side CORS issues."
)
async def proxy_thumbnail(url: Annotated[str, Query(description="Direct Instagram CDN image URL")]):
    """Proxy Instagram CDN thumbnails to bypass CORS/hotlink restrictions."""
    parsed = urlparse(url)
    allowed_hosts = (
        "cdninstagram.com",
        "fbcdn.net",
        "akamaihd.net",
        "instagram.com",
    )

    if not parsed.scheme.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")
    if not any(host in (parsed.hostname or "") for host in allowed_hosts):
        raise HTTPException(status_code=400, detail="URL host not allowed")

    try:
        resp = requests.get(url, stream=True, timeout=20)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch thumbnail")
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return StreamingResponse(resp.iter_content(chunk_size=32768), media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Proxy thumbnail failed")
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "/profile/{username}/posts",
    response_model=PostListResponse,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="List Profile Posts",
    description="Returns a list of posts with thumbnails for an Instagram user."
)
async def list_profile_posts(
    username: str,
    max_posts: Annotated[int, Query(ge=1, le=50, description="Maximum number of posts to return")] = 12,
):
    """List posts from a profile with thumbnail URLs."""
    try:
        service = get_insta_service()
        return service.list_posts(username, max_posts=max_posts)
    except InstagramDownloaderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.exception("Unexpected error listing posts")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/download/all/{username}",
    responses={
        200: {"content": {"application/zip": {}}, "description": "ZIP file"},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Download All Content",
    description="Downloads profile picture and posts in a single ZIP file."
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
    "/download/post",
    responses={
        200: {"content": {"application/zip": {}, "image/jpeg": {}, "video/mp4": {}}, "description": "Post file or ZIP"},
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Download Post by Link",
    description="Downloads a single Instagram post by URL. Returns raw media when the post has one file; returns a ZIP for multi-item posts."
)
async def download_post_by_link(
    url: Annotated[str, Query(description="Instagram post link or shortcode")],
    background_tasks: BackgroundTasks,
    include_metadata: Annotated[bool, Query(description="Include metadata files")] = True,
):
    """Download a post via link or shortcode; single media returns file, sidecars return ZIP."""
    start_time = time.time()
    temp_dir = None
    
    try:
        service = get_insta_service()
        temp_dir = create_temp_download_dir("post")
        result = service.download_post_by_url(url, temp_dir, include_metadata=include_metadata)

        media_files = result.get("media_files", [])
        if not media_files:
            cleanup_directory(temp_dir)
            raise HTTPException(status_code=404, detail="No media found for this post.")

        multiple_media = (
            result.get("is_sidecar")
            or (result.get("mediacount") and result["mediacount"] > 1)
            or len(media_files) > 1
        )

        if multiple_media:
            zip_path = create_zip_archive(result["post_folder"], result["shortcode"], temp_dir)
            schedule_cleanup(temp_dir, settings.CLEANUP_AFTER_SECONDS)
            return FileResponse(
                path=zip_path,
                media_type="application/zip",
                filename=f"{result['shortcode']}.zip",
                headers={
                    "X-Download-Shortcode": result["shortcode"],
                    "X-Download-Media-Count": str(len(media_files)),
                    "X-Download-Time-Seconds": f"{time.time() - start_time:.2f}",
                }
            )

        file_path = media_files[0]
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
        }
        media_type = media_type_map.get(file_path.suffix.lower(), "application/octet-stream")

        schedule_cleanup(temp_dir, settings.CLEANUP_AFTER_SECONDS)

        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=f"{result['shortcode']}{file_path.suffix.lower()}",
            headers={
                "X-Download-Shortcode": result["shortcode"],
                "X-Download-Media-Count": "1",
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
        logger.exception("Unexpected error during post link download")
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
