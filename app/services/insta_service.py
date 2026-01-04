"""Instaloader service for downloading Instagram content."""

import os
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Generator
from contextlib import contextmanager
import threading

import instaloader
from instaloader import Profile, Post, StoryItem
from instaloader.exceptions import (
    ProfileNotExistsException,
    PrivateProfileNotFollowedException,
    LoginRequiredException,
    ConnectionException,
    QueryReturnedBadRequestException,
)

from app.config import settings
from app.exceptions import (
    UserNotFoundError,
    PrivateProfileError,
    ProfileSuspendedError,
    RateLimitError,
    LoginRequiredError,
    DownloadError,
    NoContentError,
)
from app.models import ProfileInfo, PostMetadata

logger = logging.getLogger(__name__)


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
        
        # Try to load session if credentials are provided
        self._try_login()
    
    def _try_login(self) -> bool:
        """Attempt to login with provided credentials."""
        if settings.INSTAGRAM_SESSION_FILE and Path(settings.INSTAGRAM_SESSION_FILE).exists():
            try:
                self.loader.load_session_from_file(
                    settings.INSTAGRAM_USERNAME or "",
                    settings.INSTAGRAM_SESSION_FILE
                )
                logger.info("Session loaded successfully")
                return True
            except Exception as e:
                logger.warning(f"Failed to load session: {e}")
        
        if settings.INSTAGRAM_USERNAME and settings.INSTAGRAM_PASSWORD:
            try:
                self.loader.login(settings.INSTAGRAM_USERNAME, settings.INSTAGRAM_PASSWORD)
                logger.info("Login successful")
                return True
            except Exception as e:
                logger.warning(f"Login failed: {e}")
        
        return False
    
    @property
    def is_logged_in(self) -> bool:
        """Check if currently logged in."""
        return self.loader.context.is_logged_in
    
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
            profile = Profile.from_username(self.loader.context, username)
            return profile
        except ProfileNotExistsException:
            raise UserNotFoundError(username)
        except QueryReturnedBadRequestException:
            raise ProfileSuspendedError(username)
        except ConnectionException as e:
            if "429" in str(e):
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
        
        if profile.is_private and not self.is_logged_in:
            raise PrivateProfileError(username)
        
        target_dir.mkdir(parents=True, exist_ok=True)
        posts_metadata = []
        
        try:
            posts = profile.get_posts()
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
        except LoginRequiredException:
            raise LoginRequiredError("downloading posts")
        except ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
        
        return posts_metadata
    
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
        post_folder.mkdir(parents=True, exist_ok=True)
        
        # Download media
        try:
            self.loader.download_post(post, target=post_folder)
        except Exception as e:
            logger.warning(f"Error downloading post media: {e}")
        
        # Move files from subfolder if created
        for item in post_folder.glob("*/*"):
            if item.is_file():
                shutil.move(str(item), str(post_folder / item.name))
        
        # Clean up empty subdirectories
        for subdir in post_folder.iterdir():
            if subdir.is_dir():
                try:
                    subdir.rmdir()
                except:
                    pass
        
        # Create metadata
        metadata = PostMetadata(
            shortcode=post.shortcode,
            post_date=post_date,
            caption=post.caption if post.caption else None,
            hashtags=list(post.caption_hashtags) if post.caption_hashtags else [],
            likes=post.likes,
            comments=post.comments,
            is_video=post.is_video,
            video_view_count=post.video_view_count if post.is_video else None,
            location=post.location.name if post.location else None,
        )
        
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
    
    def download_stories(
        self, 
        username: str, 
        target_dir: Path
    ) -> int:
        """
        Download current stories from a profile.
        
        Args:
            username: Instagram username
            target_dir: Directory to save stories
            
        Returns:
            Number of stories downloaded
        """
        if not self.is_logged_in:
            raise LoginRequiredError("downloading stories")
        
        profile = self.get_profile(username)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        story_count = 0
        
        try:
            stories = self.loader.get_stories(userids=[profile.userid])
            
            for story in stories:
                for item in story.get_items():
                    try:
                        # Create folder with date-id format
                        item_date = item.date_local
                        date_str = item_date.strftime("%Y-%m-%d")
                        story_folder = target_dir / f"{date_str}-{item.mediaid}"
                        story_folder.mkdir(parents=True, exist_ok=True)
                        
                        self.loader.download_storyitem(item, story_folder)
                        story_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to download story item: {e}")
                        continue
                        
        except LoginRequiredException:
            raise LoginRequiredError("downloading stories")
        except ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Story download error: {str(e)}")
        
        return story_count
    
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
            "stories": 0,
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
        
        # Download stories (requires login)
        try:
            stories_dir = target_dir / "stories"
            stats["stories"] = self.download_stories(username, stories_dir)
        except LoginRequiredError:
            stats["errors"].append("Stories: Login required")
        except Exception as e:
            stats["errors"].append(f"Stories: {str(e)}")
        
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
