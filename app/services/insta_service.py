"""Instaloader service for downloading Instagram content."""

import os
import re
import shutil
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Generator
from contextlib import contextmanager
import threading

import instaloader
from instaloader import Profile, Post
from instaloader.exceptions import (
    ProfileNotExistsException,
    PrivateProfileNotFollowedException,
    ConnectionException,
    QueryReturnedBadRequestException,
)

from app.config import settings
from app.exceptions import (
    UserNotFoundError,
    PrivateProfileError,
    ProfileSuspendedError,
    RateLimitError,
    DownloadError,
    NoContentError,
)
from app.models import ProfileInfo, PostMetadata, PostListResponse

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}


class InstaService:
    """Service for interacting with Instagram via Instaloader."""
    
    _lock = threading.Lock()
    _instances: dict[int, 'InstaService'] = {}
    
    def __init__(self):
        """Initialize the Instaloader instance."""
        self.loader = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            max_connection_attempts=3,
            request_timeout=60,
            quiet=True,
        )
        # Harden requests with custom UA and optional session to reduce 401/429s
        user_agent = settings.IG_USER_AGENT or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        self.loader.context._default_user_agent = user_agent
        self.loader.context._session.headers.update(
            {
                "User-Agent": user_agent,
                "Referer": "https://www.instagram.com/",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        sessionid = settings.IG_SESSIONID
        if sessionid:
            self.loader.context._session.cookies.set(
                "sessionid", sessionid, domain=".instagram.com"
            )
            self.loader.context._session.cookies.set(
                "sessionid", sessionid, domain="www.instagram.com"
            )

        self._proxy_cycle = self._build_proxy_cycle(settings.PROXIES)
        if self._proxy_cycle:
            self._apply_next_proxy()

    def _build_proxy_cycle(self, proxies: list[str]):
        """Return an endless cycle over proxies; empty list returns None."""
        if not proxies:
            return None
        return iter(proxies * 1000)  # simple deterministic cycle without itertools

    def _apply_next_proxy(self):
        """Rotate proxy for the session if pool is configured."""
        if not self._proxy_cycle:
            return
        try:
            proxy = next(self._proxy_cycle)
            if proxy:
                self.loader.context._session.proxies.update({
                    "http": proxy,
                    "https": proxy,
                })
                logger.info(f"Using proxy: {proxy}")
        except StopIteration:
            pass

    def _with_backoff(self, func, *args, **kwargs):
        """Execute func with retry/backoff and proxy rotation on failure."""
        attempts = settings.PROXY_RETRY_MAX
        base = settings.PROXY_BACKOFF_BASE
        jitter = settings.PROXY_BACKOFF_JITTER

        for attempt in range(1, attempts + 1):
            try:
                return func(*args, **kwargs)
            except ConnectionException as e:
                # Treat Instagram throttle as rate limit
                msg = str(e)
                if "429" in msg or "Please wait a few minutes" in msg:
                    if attempt == attempts:
                        raise RateLimitError()
                    sleep_for = base ** attempt + random.uniform(0, jitter)
                    logger.warning(
                        f"Rate limited (attempt {attempt}/{attempts}); backing off {sleep_for:.2f}s"
                    )
                    time.sleep(sleep_for)
                    if settings.PROXY_ROTATION:
                        self._apply_next_proxy()
                    continue
                if attempt == attempts:
                    raise DownloadError(f"Connection error: {msg}")
                sleep_for = base ** attempt + random.uniform(0, jitter)
                time.sleep(sleep_for)
                if settings.PROXY_ROTATION:
                    self._apply_next_proxy()
            except Exception:
                raise
        raise DownloadError("Unable to complete request after retries")
    
    def get_profile(self, username: str) -> Profile:
        """
        Get Instagram profile by username.
        
        Args:
            username: Instagram username
            
        Returns:
            Profile object
            
        Raises:
            UserNotFoundError: If user doesn't exist
            ProfileSuspendedError: If profile is suspended
        """
        try:
            profile = self._with_backoff(Profile.from_username, self.loader.context, username)
            return profile
        except ProfileNotExistsException:
            raise UserNotFoundError(username)
        except QueryReturnedBadRequestException:
            raise ProfileSuspendedError(username)
        except ConnectionException as e:
            if "429" in str(e) or "Please wait a few minutes" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
    
    def get_profile_info(self, username: str) -> ProfileInfo:
        """Get profile information."""
        profile = self.get_profile(username)
        
        return ProfileInfo(
            username=profile.username,
            full_name=profile.full_name or None,
            biography=profile.biography or None,
            followers=profile.followers,
            following=profile.followees,
            post_count=profile.mediacount,
            is_private=profile.is_private,
            is_verified=profile.is_verified,
            profile_pic_url=profile.profile_pic_url,
            external_url=profile.external_url or None,
        )
    
    def list_posts(self, username: str, max_posts: int = 12) -> PostListResponse:
        """
        List posts from a profile with thumbnail URLs.
        
        Args:
            username: Instagram username
            max_posts: Maximum number of posts to return (default 12)
            
        Returns:
            PostListResponse with post list
        """
        profile = self.get_profile(username)
        
        if profile.is_private:
            raise PrivateProfileError(username)
        
        posts_list = []
        
        try:
            posts = self._with_backoff(profile.get_posts)
            count = 0
            
            for post in posts:
                if count >= max_posts:
                    break
                
                try:
                    # Get thumbnail URL
                    thumbnail_url = post.url  # This is the display URL for the post
                    post_url = f"https://www.instagram.com/p/{post.shortcode}/"
                    
                    metadata = PostMetadata(
                        shortcode=post.shortcode,
                        post_date=post.date_local,
                        caption=post.caption if post.caption else None,
                        hashtags=list(post.caption_hashtags) if post.caption_hashtags else [],
                        likes=post.likes,
                        comments=post.comments,
                        is_video=post.is_video,
                        video_view_count=post.video_view_count if post.is_video else None,
                        location=post.location.name if post.location else None,
                        thumbnail_url=thumbnail_url,
                        post_url=post_url,
                    )
                    posts_list.append(metadata)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to get post info {post.shortcode}: {e}")
                    continue
                    
        except PrivateProfileNotFollowedException:
            raise PrivateProfileError(username)
        except ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
        
        return PostListResponse(
            username=username,
            total_posts=profile.mediacount,
            returned_posts=len(posts_list),
            posts=posts_list,
        )
    
    def download_profile_pic(self, username: str, target_dir: Path) -> Path | None:
        """
        Download profile picture.
        
        Args:
            username: Instagram username
            target_dir: Directory to save the picture
            
        Returns:
            Path to downloaded file or None if failed
        """
        profile = self.get_profile(username)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Use direct URL download - more reliable than instaloader's method
        try:
            import requests
            
            # Get HD profile pic URL
            pic_url = profile.profile_pic_url
            if pic_url:
                response = requests.get(pic_url, timeout=30)
                response.raise_for_status()
                
                # Determine extension from content type or URL
                content_type = response.headers.get('content-type', '')
                if 'png' in content_type:
                    ext = '.png'
                elif 'webp' in content_type:
                    ext = '.webp'
                else:
                    ext = '.jpg'
                
                dest = target_dir / f"profile_pic{ext}"
                dest.write_bytes(response.content)
                logger.info(f"Profile pic downloaded successfully: {dest}")
                return dest
        except Exception as e:
            logger.warning(f"Direct download failed: {e}")
        
        # Fallback: Use instaloader's method with proper directory handling
        try:
            original_cwd = Path.cwd()
            os.chdir(target_dir)
            
            try:
                self.loader.download_profilepic(profile)
                
                # Find the downloaded file
                for file in target_dir.glob(f"{username}*"):
                    if file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                        dest = target_dir / f"profile_pic{file.suffix}"
                        if file != dest:
                            shutil.move(str(file), str(dest))
                        return dest
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            logger.error(f"Instaloader download also failed: {e}")
        
        return None
    
    def download_posts(
        self, 
        username: str, 
        target_dir: Path,
        max_posts: int | None = None,
        include_metadata: bool = True
    ) -> list[PostMetadata]:
        """
        Download all posts from a profile.
        
        Args:
            username: Instagram username
            target_dir: Directory to save posts
            max_posts: Maximum number of posts to download
            include_metadata: Whether to save metadata files
            
        Returns:
            List of PostMetadata for downloaded posts
        """
        profile = self.get_profile(username)
        
        if profile.is_private:
            raise PrivateProfileError(username)
        
        target_dir.mkdir(parents=True, exist_ok=True)
        posts_metadata = []
        
        try:
            posts = self._with_backoff(profile.get_posts)
            count = 0
            
            for post in posts:
                if max_posts and count >= max_posts:
                    break
                
                try:
                    metadata = self._download_single_post(
                        post, target_dir, include_metadata
                    )
                    if metadata:
                        posts_metadata.append(metadata)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to download post {post.shortcode}: {e}")
                    continue
                    
        except PrivateProfileNotFollowedException:
            raise PrivateProfileError(username)
        except ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
        
        return posts_metadata

    def download_post_by_url(
        self,
        url_or_shortcode: str,
        target_dir: Path,
        include_metadata: bool = True
    ) -> dict:
        """Download a single post by its URL or shortcode."""
        shortcode = self._extract_shortcode(url_or_shortcode)

        try:
            post = self._with_backoff(Post.from_shortcode, self.loader.context, shortcode)
        except PrivateProfileNotFollowedException:
            raise PrivateProfileError("This profile")
        except ProfileNotExistsException:
            raise DownloadError("Post not found or unreachable.")
        except ConnectionException as e:
            if "429" in str(e) or "Please wait a few minutes" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")

        try:
            owner_profile = post.owner_profile
        except Exception:
            owner_profile = None

        if owner_profile and owner_profile.is_private:
            raise PrivateProfileError(post.owner_username)

        post_folder = target_dir / f"{post.date_local.strftime('%Y-%m-%d')}-{post.shortcode}"
        media_files = self._download_post_media(post, post_folder)
        metadata = self._build_post_metadata(post)

        if include_metadata:
            self._save_metadata(metadata, post_folder / "metadata.txt")

        return {
            "shortcode": post.shortcode,
            "owner": post.owner_username,
            "media_files": media_files,
            "post_folder": post_folder,
            "metadata": metadata,
            "is_sidecar": post.typename == "GraphSidecar",
            "mediacount": getattr(post, "mediacount", None),
        }
    
    def _download_single_post(
        self, 
        post: Post, 
        target_dir: Path,
        include_metadata: bool = True
    ) -> PostMetadata | None:
        """Download a single post with its media and metadata."""
        # Create folder with date-id format
        post_date = post.date_local
        date_str = post_date.strftime("%Y-%m-%d")
        post_folder = target_dir / f"{date_str}-{post.shortcode}"
        self._download_post_media(post, post_folder)

        metadata = self._build_post_metadata(post)

        if include_metadata:
            self._save_metadata(metadata, post_folder / "metadata.txt")
        
        return metadata
    
    def _save_metadata(self, metadata: PostMetadata, filepath: Path) -> None:
        """Save post metadata to a text file."""
        content = f"""Post Information
==================

Shortcode: {metadata.shortcode}
Post Date: {metadata.post_date.strftime("%Y-%m-%d %H:%M:%S")}
Likes: {metadata.likes}
Comments: {metadata.comments}
Video: {"Yes" if metadata.is_video else "No"}
"""
        
        if metadata.is_video and metadata.video_view_count:
            content += f"Video Views: {metadata.video_view_count}\n"
        
        if metadata.location:
            content += f"Location: {metadata.location}\n"
        
        content += f"\nHashtags: {', '.join(metadata.hashtags) if metadata.hashtags else 'None'}\n"
        content += f"\nCaption:\n{'-' * 40}\n{metadata.caption or '(No caption)'}\n"
        
        filepath.write_text(content, encoding="utf-8")

    def _extract_shortcode(self, identifier: str) -> str:
        """Extract shortcode from a post URL or return the identifier if it already is one."""
        shortcode_pattern = re.compile(
            r"(?:instagram\.com/(?:p|reel|tv)/|/p/|/reel/|/tv/|/stories/[^/]+/)([A-Za-z0-9_-]{5,})",
            re.IGNORECASE,
        )
        match = shortcode_pattern.search(identifier)
        if match:
            return match.group(1)
        if re.fullmatch(r"[A-Za-z0-9_-]{5,}", identifier):
            return identifier
        raise DownloadError("Provide a valid Instagram link or shortcode.")

    def _collect_media_files(self, post_folder: Path) -> list[Path]:
        """Return media files (photo/video) inside the given folder."""
        return [
            item
            for item in post_folder.iterdir()
            if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS
        ]

    def _build_post_metadata(self, post: Post) -> PostMetadata:
        """Create PostMetadata from an Instaloader post."""
        return PostMetadata(
            shortcode=post.shortcode,
            post_date=post.date_local,
            caption=post.caption if post.caption else None,
            hashtags=list(post.caption_hashtags) if post.caption_hashtags else [],
            likes=post.likes,
            comments=post.comments,
            is_video=post.is_video,
            video_view_count=post.video_view_count if post.is_video else None,
            location=post.location.name if post.location else None,
        )

    def _download_post_media(self, post: Post, post_folder: Path) -> list[Path]:
        """Download post media to the given folder and return media file paths."""
        post_folder.mkdir(parents=True, exist_ok=True)

        try:
            self.loader.download_post(post, target=post_folder)
        except Exception as e:
            logger.warning(f"Error downloading post media: {e}")

        for item in post_folder.glob("*/*"):
            if item.is_file():
                shutil.move(str(item), str(post_folder / item.name))

        for subdir in post_folder.iterdir():
            if subdir.is_dir():
                try:
                    subdir.rmdir()
                except Exception:
                    pass

        return self._collect_media_files(post_folder)
    
    def download_all(
        self,
        username: str,
        target_dir: Path,
        max_posts: int | None = None,
        include_metadata: bool = True
    ) -> dict:
        """
        Download all available content from a profile.
        
        Args:
            username: Instagram username
            target_dir: Base directory for downloads
            max_posts: Maximum posts to download
            include_metadata: Include metadata files
            
        Returns:
            Dictionary with download statistics
        """
        stats = {
            "posts": 0,
            "profile_pic": False,
            "errors": []
        }
        
        # Download profile picture
        try:
            pic_path = self.download_profile_pic(username, target_dir)
            stats["profile_pic"] = pic_path is not None
        except Exception as e:
            stats["errors"].append(f"Profile picture: {str(e)}")
        
        # Download posts
        try:
            posts_dir = target_dir / "posts"
            posts = self.download_posts(
                username, 
                posts_dir, 
                max_posts=max_posts,
                include_metadata=include_metadata
            )
            stats["posts"] = len(posts)
        except PrivateProfileError:
            stats["errors"].append("Posts: Profile is private")
        except Exception as e:
            stats["errors"].append(f"Posts: {str(e)}")
        
        return stats


# Thread-safe instance getter
def get_insta_service() -> InstaService:
    """Get or create InstaService instance."""
    thread_ident = threading.current_thread().ident
    thread_id = thread_ident if thread_ident is not None else -1
    
    with InstaService._lock:
        if thread_id not in InstaService._instances:
            InstaService._instances[thread_id] = InstaService()
        return InstaService._instances[thread_id]
