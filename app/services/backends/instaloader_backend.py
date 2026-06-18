"""Instaloader backend implementation."""

import os
import re
import shutil
import logging
from datetime import datetime
from pathlib import Path

import requests

from app.config import settings
from app.exceptions import (
    UserNotFoundError,
    PrivateProfileError,
    ProfileSuspendedError,
    RateLimitError,
    DownloadError,
)
from app.models import ProfileInfo, PostMetadata, PostListResponse, FollowerEntry, FollowerListResponse

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}


class InstaloaderBackend:
    """Instaloader backend implementation."""
    
    def __init__(self):
        self._init_instaloader()
    
    def _init_instaloader(self):
        try:
            import instaloader
            from instaloader.exceptions import (
                ProfileNotExistsException,
                PrivateProfileNotFollowedException,
                ConnectionException,
                QueryReturnedBadRequestException,
            )
            
            self.instaloader = instaloader
            self.ProfileNotExistsException = ProfileNotExistsException
            self.PrivateProfileNotFollowedException = PrivateProfileNotFollowedException
            self.ConnectionException = ConnectionException
            self.QueryReturnedBadRequestException = QueryReturnedBadRequestException
            
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
            
            user_agent = settings.IG_USER_AGENT or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            self.loader.context.user_agent = user_agent
            self.loader.context._session.headers.update({
                "User-Agent": user_agent,
                "Referer": "https://www.instagram.com/",
                "Accept-Language": "en-US,en;q=0.9",
            })
            
            sessionid = settings.IG_SESSIONID
            if sessionid:
                self.loader.context._session.cookies.set(
                    "sessionid", sessionid, domain=".instagram.com"
                )
                self.loader.context._session.cookies.set(
                    "sessionid", sessionid, domain="www.instagram.com"
                )
            
            if settings.IG_USERNAME and settings.IG_PASSWORD:
                try:
                    self.loader.login(settings.IG_USERNAME, settings.IG_PASSWORD)
                    logger.info(f"Instaloader: Logged in as {settings.IG_USERNAME}")
                except Exception as e:
                    logger.warning(f"Instaloader: Login failed: {e}")
            
            self._available = True
            
        except ImportError as e:
            logger.warning(f"Instaloader not available: {e}")
            self._available = False
    
    @property
    def available(self) -> bool:
        return self._available
    
    def get_profile(self, username: str):
        try:
            profile = self.instaloader.Profile.from_username(self.loader.context, username)
            return profile
        except self.ProfileNotExistsException:
            raise UserNotFoundError(username)
        except self.QueryReturnedBadRequestException:
            raise ProfileSuspendedError(username)
        except self.ConnectionException as e:
            if "429" in str(e) or "Please wait a few minutes" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
    
    def get_profile_info(self, username: str) -> ProfileInfo:
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
        profile = self.get_profile(username)
        if profile.is_private:
            raise PrivateProfileError(username)
        
        posts_list = []
        try:
            posts = profile.get_posts()
            count = 0
            for post in posts:
                if count >= max_posts:
                    break
                try:
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
                        thumbnail_url=post.url,
                        post_url=f"https://www.instagram.com/p/{post.shortcode}/",
                    )
                    posts_list.append(metadata)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to get post info {post.shortcode}: {e}")
                    continue
        except self.PrivateProfileNotFollowedException:
            raise PrivateProfileError(username)
        except self.ConnectionException as e:
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
        profile = self.get_profile(username)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            pic_url = profile.profile_pic_url
            if pic_url:
                headers = {
                    "User-Agent": settings.IG_USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    "Referer": "https://www.instagram.com/",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                }
                response = requests.get(pic_url, headers=headers, timeout=30)
                response.raise_for_status()
                
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
            logger.warning(f"Direct URL download failed: {e}")
        
        try:
            original_cwd = Path.cwd()
            os.chdir(target_dir)
            try:
                self.loader.download_profilepic(profile)
                for file in target_dir.glob(f"{username}*"):
                    if file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                        dest = target_dir / f"profile_pic{file.suffix}"
                        if file != dest:
                            shutil.move(str(file), str(dest))
                        return dest
            finally:
                os.chdir(original_cwd)
        except Exception as e:
            logger.error(f"Instaloader download_profilepic failed: {e}")
        
        return None
    
    def download_posts(self, username: str, target_dir: Path, max_posts: int | None = None, include_metadata: bool = True) -> list[PostMetadata]:
        profile = self.get_profile(username)
        if profile.is_private:
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
                    metadata = self._download_single_post(post, target_dir, include_metadata)
                    if metadata:
                        posts_metadata.append(metadata)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to download post {post.shortcode}: {e}")
                    continue
        except self.PrivateProfileNotFollowedException:
            raise PrivateProfileError(username)
        except self.ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
        
        return posts_metadata
    
    def _download_single_post(self, post, target_dir: Path, include_metadata: bool = True) -> PostMetadata | None:
        post_date = post.date_local
        date_str = post_date.strftime("%Y-%m-%d")
        post_folder = target_dir / f"{date_str}-{post.shortcode}"
        self._download_post_media(post, post_folder)
        
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
        )
        
        if include_metadata:
            self._save_metadata(metadata, post_folder / "metadata.txt")
        
        return metadata
    
    def _download_post_media(self, post, post_folder: Path) -> list[Path]:
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
        
        return [f for f in post_folder.iterdir() if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS]
    
    def _save_metadata(self, metadata: PostMetadata, filepath: Path) -> None:
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
    
    def get_followers(self, username: str, max_count: int | None = None) -> FollowerListResponse:
        profile = self.get_profile(username)
        if profile.is_private:
            raise PrivateProfileError(username)
        
        followers_list = []
        try:
            followers = profile.get_followers()
            count = 0
            for follower in followers:
                if max_count and count >= max_count:
                    break
                try:
                    entry = FollowerEntry(
                        username=follower.username,
                        full_name=follower.full_name or None,
                        is_private=follower.is_private,
                        is_verified=follower.is_verified,
                        profile_pic_url=follower.profile_pic_url,
                    )
                    followers_list.append(entry)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to get follower info: {e}")
                    continue
        except self.PrivateProfileNotFollowedException:
            raise PrivateProfileError(username)
        except self.ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
        
        return FollowerListResponse(
            username=username,
            list_type="followers",
            total_count=profile.followers,
            returned_count=len(followers_list),
            users=followers_list,
        )
    
    def get_following(self, username: str, max_count: int | None = None) -> FollowerListResponse:
        profile = self.get_profile(username)
        if profile.is_private:
            raise PrivateProfileError(username)
        
        following_list = []
        try:
            following = profile.get_followees()
            count = 0
            for followee in following:
                if max_count and count >= max_count:
                    break
                try:
                    entry = FollowerEntry(
                        username=followee.username,
                        full_name=followee.full_name or None,
                        is_private=followee.is_private,
                        is_verified=followee.is_verified,
                        profile_pic_url=followee.profile_pic_url,
                    )
                    following_list.append(entry)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to get following info: {e}")
                    continue
        except self.PrivateProfileNotFollowedException:
            raise PrivateProfileError(username)
        except self.ConnectionException as e:
            if "429" in str(e):
                raise RateLimitError()
            raise DownloadError(f"Connection error: {str(e)}")
        
        return FollowerListResponse(
            username=username,
            list_type="following",
            total_count=profile.followees,
            returned_count=len(following_list),
            users=following_list,
        )
    
    def download_post_by_shortcode(self, shortcode: str, target_dir: Path, include_metadata: bool = True) -> dict:
        try:
            post = self.instaloader.Post.from_shortcode(self.loader.context, shortcode)
        except self.PrivateProfileNotFollowedException:
            raise PrivateProfileError("This profile")
        except self.ProfileNotExistsException:
            raise DownloadError("Post not found or unreachable.")
        except self.ConnectionException as e:
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
        )
        
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
