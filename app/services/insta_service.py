"""Combined Instagram service using Instaloader and Instagrapi with fallback."""

import re
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.exceptions import (
    UserNotFoundError,
    PrivateProfileError,
    ProfileSuspendedError,
    DownloadError,
    NoContentError,
)
from app.models import ProfileInfo, PostMetadata, PostListResponse, FollowerEntry, FollowerListResponse
from app.services.backends import InstaloaderBackend, InstagrapiBackend

logger = logging.getLogger(__name__)


class InstaService:
    """Combined Instagram service with fallback between backends."""
    
    _lock = threading.Lock()
    _instances: dict[int, 'InstaService'] = {}
    
    def __init__(self):
        self.instaloader = InstaloaderBackend()
        self.instagrapi = InstagrapiBackend()
        self._instaloader_available = self.instaloader.available
        self._instagrapi_available = self.instagrapi.available
        
        if not self._instaloader_available and not self._instagrapi_available:
            raise RuntimeError("No Instagram backend available. Install instaloader or instagrapi.")
        
        logger.info(f"InstaService initialized - Instaloader: {self._instaloader_available}, Instagrapi: {self._instagrapi_available}")
    
    def _try_backends(self, instaloader_func: Callable, instagrapi_func: Callable, *args, **kwargs) -> Any:
        """Try both backends with fallback."""
        primary = settings.IG_PRIMARY_LIBRARY.lower()
        errors = []
        
        backends = []
        if primary == "instaloader":
            if self._instaloader_available:
                backends.append(("instaloader", instaloader_func))
            if self._instagrapi_available:
                backends.append(("instagrapi", instagrapi_func))
        else:
            if self._instagrapi_available:
                backends.append(("instagrapi", instagrapi_func))
            if self._instaloader_available:
                backends.append(("instaloader", instaloader_func))
        
        for name, func in backends:
            try:
                logger.info(f"Trying {name} backend")
                return func(*args, **kwargs)
            except (UserNotFoundError, PrivateProfileError, ProfileSuspendedError, NoContentError):
                raise
            except Exception as e:
                logger.warning(f"{name} backend failed: {e}")
                errors.append(f"{name}: {str(e)}")
                continue
        
        raise DownloadError(f"All backends failed: {'; '.join(errors)}")
    
    def get_profile_info(self, username: str) -> ProfileInfo:
        return self._try_backends(
            self.instaloader.get_profile_info,
            self.instagrapi.get_profile_info,
            username
        )
    
    def list_posts(self, username: str, max_posts: int = 12) -> PostListResponse:
        return self._try_backends(
            self.instaloader.list_posts,
            self.instagrapi.list_posts,
            username,
            max_posts
        )
    
    def download_profile_pic(self, username: str, target_dir: Path) -> Path | None:
        return self._try_backends(
            self.instaloader.download_profile_pic,
            self.instagrapi.download_profile_pic,
            username,
            target_dir
        )
    
    def download_posts(self, username: str, target_dir: Path, max_posts: int | None = None, include_metadata: bool = True) -> list[PostMetadata]:
        return self._try_backends(
            self.instaloader.download_posts,
            self.instagrapi.download_posts,
            username,
            target_dir,
            max_posts,
            include_metadata
        )
    
    def get_followers(self, username: str, max_count: int | None = None) -> FollowerListResponse:
        return self._try_backends(
            self.instaloader.get_followers,
            self.instagrapi.get_followers,
            username,
            max_count
        )
    
    def get_following(self, username: str, max_count: int | None = None) -> FollowerListResponse:
        return self._try_backends(
            self.instaloader.get_following,
            self.instagrapi.get_following,
            username,
            max_count
        )
    
    def download_followers(self, username: str, target_dir: Path, max_count: int | None = None, include_metadata: bool = True) -> FollowerListResponse:
        target_dir.mkdir(parents=True, exist_ok=True)
        followers_data = self.get_followers(username, max_count=max_count)
        
        if include_metadata:
            self._save_followers_metadata(followers_data, target_dir / "followers.txt")
        
        return followers_data
    
    def download_following(self, username: str, target_dir: Path, max_count: int | None = None, include_metadata: bool = True) -> FollowerListResponse:
        target_dir.mkdir(parents=True, exist_ok=True)
        following_data = self.get_following(username, max_count=max_count)
        
        if include_metadata:
            self._save_followers_metadata(following_data, target_dir / "following.txt")
        
        return following_data
    
    def _save_followers_metadata(self, data: FollowerListResponse, filepath: Path) -> None:
        content = f"""{data.list_type.title()} List for @{data.username}
========================================

Total Count: {data.total_count}
Returned Count: {data.returned_count}

List:
------
"""
        for user in data.users:
            line = f"@{user.username}"
            if user.full_name:
                line += f" - {user.full_name}"
            if user.is_verified:
                line += " ✓"
            if user.is_private:
                line += " 🔒"
            content += line + "\n"
        
        filepath.write_text(content, encoding="utf-8")
    
    def download_post_by_url(self, url_or_shortcode: str, target_dir: Path, include_metadata: bool = True) -> dict:
        shortcode = self._extract_shortcode(url_or_shortcode)
        return self._try_backends(
            lambda: self.instaloader.download_post_by_shortcode(shortcode, target_dir, include_metadata),
            lambda: self.instagrapi.download_post_by_shortcode(shortcode, target_dir, include_metadata)
        )
    
    def _extract_shortcode(self, identifier: str) -> str:
        identifier = identifier.strip()
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
    
    def download_all(
        self,
        username: str,
        target_dir: Path,
        max_posts: int | None = None,
        max_followers: int | None = None,
        max_following: int | None = None,
        include_metadata: bool = True
    ) -> dict:
        stats = {
            "posts": 0,
            "profile_pic": False,
            "followers": 0,
            "following": 0,
            "errors": []
        }
        
        try:
            pic_path = self.download_profile_pic(username, target_dir)
            stats["profile_pic"] = pic_path is not None
        except Exception as e:
            stats["errors"].append(f"Profile picture: {str(e)}")
        
        try:
            posts_dir = target_dir / "posts"
            posts = self.download_posts(username, posts_dir, max_posts=max_posts, include_metadata=include_metadata)
            stats["posts"] = len(posts)
        except PrivateProfileError:
            stats["errors"].append("Posts: Profile is private")
        except Exception as e:
            stats["errors"].append(f"Posts: {str(e)}")
        
        try:
            followers_dir = target_dir / "followers"
            followers = self.download_followers(username, followers_dir, max_count=max_followers, include_metadata=include_metadata)
            stats["followers"] = followers.returned_count
        except PrivateProfileError:
            stats["errors"].append("Followers: Profile is private")
        except Exception as e:
            stats["errors"].append(f"Followers: {str(e)}")
        
        try:
            following_dir = target_dir / "following"
            following = self.download_following(username, following_dir, max_count=max_following, include_metadata=include_metadata)
            stats["following"] = following.returned_count
        except PrivateProfileError:
            stats["errors"].append("Following: Profile is private")
        except Exception as e:
            stats["errors"].append(f"Following: {str(e)}")
        
        return stats


def get_insta_service() -> InstaService:
    """Get or create InstaService instance."""
    thread_ident = threading.current_thread().ident
    thread_id = thread_ident if thread_ident is not None else -1
    
    with InstaService._lock:
        if thread_id not in InstaService._instances:
            InstaService._instances[thread_id] = InstaService()
        return InstaService._instances[thread_id]
