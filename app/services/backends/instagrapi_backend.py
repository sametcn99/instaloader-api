"""Instagrapi backend implementation."""

import os
import re
import logging
from datetime import datetime
from pathlib import Path

import requests

from app.config import settings
from app.exceptions import (
    UserNotFoundError,
    PrivateProfileError,
    RateLimitError,
    DownloadError,
)
from app.models import ProfileInfo, PostMetadata, PostListResponse, FollowerEntry, FollowerListResponse

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}


class InstagrapiBackend:
    """Instagrapi backend implementation."""
    
    def __init__(self):
        self._init_instagrapi()
    
    def _init_instagrapi(self):
        try:
            from instagrapi import Client
            from instagrapi.exceptions import (
                LoginRequired,
                UserNotFound,
                PrivateAccount,
                ChallengeRequired,
                FeedbackRequired,
                PleaseWaitFewMinutes,
                RateLimitError as IgRateLimitError,
            )
            
            self.Client = Client
            self.LoginRequired = LoginRequired
            self.UserNotFound = UserNotFound
            self.PrivateAccount = PrivateAccount
            self.ChallengeRequired = ChallengeRequired
            self.FeedbackRequired = FeedbackRequired
            self.PleaseWaitFewMinutes = PleaseWaitFewMinutes
            self.IgRateLimitError = IgRateLimitError
            
            self.client = Client()
            
            self.client.delay_range = settings.IG_DELAY_RANGE
            
            if settings.PROXIES:
                proxy = settings.PROXIES[0]
                self.client.set_proxy(proxy)
            
            if settings.IG_SESSION_FILE and os.path.exists(settings.IG_SESSION_FILE):
                try:
                    self.client.load_settings(settings.IG_SESSION_FILE)
                    logger.info("Instagrapi: Loaded session from file")
                except Exception as e:
                    logger.warning(f"Instagrapi: Failed to load session: {e}")
            
            if settings.IG_USERNAME and settings.IG_PASSWORD:
                try:
                    self.client.login(settings.IG_USERNAME, settings.IG_PASSWORD)
                    logger.info(f"Instagrapi: Logged in as {settings.IG_USERNAME}")
                    if settings.IG_SESSION_FILE:
                        self.client.dump_settings(settings.IG_SESSION_FILE)
                except Exception as e:
                    logger.warning(f"Instagrapi: Login failed: {e}")
            elif settings.IG_SESSIONID:
                try:
                    self.client.login_by_sessionid(settings.IG_SESSIONID)
                    logger.info("Instagrapi: Logged in with sessionid")
                except Exception as e:
                    logger.warning(f"Instagrapi: Sessionid login failed: {e}")
            
            self._available = True
            
        except ImportError as e:
            logger.warning(f"Instagrapi not available: {e}")
            self._available = False
    
    @property
    def available(self) -> bool:
        return self._available
    
    def _handle_error(self, e: Exception, username: str = ""):
        if isinstance(e, self.UserNotFound):
            raise UserNotFoundError(username)
        elif isinstance(e, self.PrivateAccount):
            raise PrivateProfileError(username)
        elif isinstance(e, (self.PleaseWaitFewMinutes, self.IgRateLimitError)):
            raise RateLimitError()
        elif isinstance(e, self.FeedbackRequired):
            raise DownloadError(f"Instagram feedback required: {str(e)}")
        else:
            raise DownloadError(f"Instagrapi error: {str(e)}")
    
    def get_user_id(self, username: str) -> str:
        try:
            return self.client.user_id_from_username(username)
        except Exception as e:
            self._handle_error(e, username)
    
    def get_profile_info(self, username: str) -> ProfileInfo:
        try:
            user_id = self.get_user_id(username)
            user = self.client.user_info(user_id)
            return ProfileInfo(
                username=user.username,
                full_name=user.full_name or None,
                biography=user.biography or None,
                followers=user.follower_count,
                following=user.following_count,
                post_count=user.media_count,
                is_private=user.is_private,
                is_verified=user.is_verified,
                profile_pic_url=user.profile_pic_url.hd if hasattr(user.profile_pic_url, 'hd') else str(user.profile_pic_url),
                external_url=user.external_url or None,
            )
        except Exception as e:
            self._handle_error(e, username)
    
    def list_posts(self, username: str, max_posts: int = 12) -> PostListResponse:
        try:
            user_id = self.get_user_id(username)
            user = self.client.user_info(user_id)
            
            if user.is_private:
                raise PrivateProfileError(username)
            
            medias = self.client.user_medias(user_id, amount=max_posts)
            posts_list = []
            
            for media in medias:
                try:
                    thumbnail_url = ""
                    if hasattr(media, 'image_versions') and media.image_versions:
                        thumbnail_url = media.image_versions[0].url
                    elif hasattr(media, 'thumbnail_url') and media.thumbnail_url:
                        thumbnail_url = str(media.thumbnail_url)
                    elif hasattr(media, 'video_url') and media.video_url:
                        thumbnail_url = str(media.video_url)
                    
                    post_url = f"https://www.instagram.com/p/{media.code}/" if hasattr(media, 'code') else ""
                    
                    metadata = PostMetadata(
                        shortcode=media.code if hasattr(media, 'code') else media.id,
                        post_date=datetime.fromtimestamp(media.taken_at) if hasattr(media, 'taken_at') else datetime.now(),
                        caption=media.caption_text if hasattr(media, 'caption_text') else None,
                        hashtags=re.findall(r'#(\w+)', media.caption_text) if hasattr(media, 'caption_text') and media.caption_text else [],
                        likes=media.like_count if hasattr(media, 'like_count') else 0,
                        comments=media.comment_count if hasattr(media, 'comment_count') else 0,
                        is_video=media.media_type == 2 if hasattr(media, 'media_type') else False,
                        video_view_count=media.view_count if hasattr(media, 'view_count') else None,
                        location=media.location.name if hasattr(media, 'location') and media.location else None,
                        thumbnail_url=thumbnail_url,
                        post_url=post_url,
                    )
                    posts_list.append(metadata)
                except Exception as e:
                    logger.warning(f"Failed to get post info: {e}")
                    continue
            
            return PostListResponse(
                username=username,
                total_posts=user.media_count,
                returned_posts=len(posts_list),
                posts=posts_list,
            )
        except Exception as e:
            self._handle_error(e, username)
    
    def download_profile_pic(self, username: str, target_dir: Path) -> Path | None:
        target_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            user_id = self.get_user_id(username)
            user = self.client.user_info(user_id)
            
            pic_url = str(user.profile_pic_url)
            if hasattr(user.profile_pic_url, 'hd'):
                pic_url = user.profile_pic_url.hd
            
            headers = {
                "User-Agent": settings.IG_USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Referer": "https://www.instagram.com/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }
            response = requests.get(pic_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '')
            ext = '.jpg'
            if 'png' in content_type:
                ext = '.png'
            elif 'webp' in content_type:
                ext = '.webp'
            
            dest = target_dir / f"profile_pic{ext}"
            dest.write_bytes(response.content)
            logger.info(f"Instagrapi: Profile pic downloaded to {dest}")
            return dest
            
        except Exception as e:
            logger.error(f"Instagrapi profile pic download failed: {e}")
            return None
    
    def download_posts(self, username: str, target_dir: Path, max_posts: int | None = None, include_metadata: bool = True) -> list[PostMetadata]:
        try:
            user_id = self.get_user_id(username)
            user = self.client.user_info(user_id)
            
            if user.is_private:
                raise PrivateProfileError(username)
            
            target_dir.mkdir(parents=True, exist_ok=True)
            medias = self.client.user_medias(user_id, amount=max_posts)
            posts_metadata = []
            
            for media in medias:
                try:
                    post_folder = target_dir / f"{datetime.fromtimestamp(media.taken_at).strftime('%Y-%m-%d')}-{media.code}"
                    post_folder.mkdir(parents=True, exist_ok=True)
                    
                    if media.media_type == 1:
                        self.client.photo_download(media.id, filename=str(post_folder / "photo"))
                    elif media.media_type == 2:
                        self.client.video_download(media.id, filename=str(post_folder / "video"))
                    elif media.media_type == 8:
                        for i, resource in enumerate(media.resources):
                            if resource.media_type == 1:
                                self.client.photo_download(resource.id, filename=str(post_folder / f"photo_{i}"))
                            else:
                                self.client.video_download(resource.id, filename=str(post_folder / f"video_{i}"))
                    
                    metadata = PostMetadata(
                        shortcode=media.code,
                        post_date=datetime.fromtimestamp(media.taken_at),
                        caption=media.caption_text if hasattr(media, 'caption_text') else None,
                        hashtags=re.findall(r'#(\w+)', media.caption_text) if hasattr(media, 'caption_text') and media.caption_text else [],
                        likes=media.like_count if hasattr(media, 'like_count') else 0,
                        comments=media.comment_count if hasattr(media, 'comment_count') else 0,
                        is_video=media.media_type == 2,
                        video_view_count=media.view_count if hasattr(media, 'view_count') else None,
                        location=media.location.name if hasattr(media, 'location') and media.location else None,
                    )
                    posts_metadata.append(metadata)
                    
                    if include_metadata:
                        self._save_metadata(metadata, post_folder / "metadata.txt")
                except Exception as e:
                    logger.warning(f"Failed to download post {media.code}: {e}")
                    continue
            
            return posts_metadata
        except Exception as e:
            self._handle_error(e, username)
    
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
        try:
            user_id = self.get_user_id(username)
            user = self.client.user_info(user_id)
            
            if user.is_private:
                raise PrivateProfileError(username)
            
            followers = self.client.user_followers(user_id, amount=max_count)
            followers_list = []
            
            for pk, user_short in followers.items():
                try:
                    entry = FollowerEntry(
                        username=user_short.username,
                        full_name=user_short.full_name or None,
                        is_private=user_short.is_private,
                        is_verified=user_short.is_verified,
                        profile_pic_url=user_short.profile_pic_url,
                    )
                    followers_list.append(entry)
                except Exception as e:
                    logger.warning(f"Failed to get follower info: {e}")
                    continue
            
            return FollowerListResponse(
                username=username,
                list_type="followers",
                total_count=user.follower_count,
                returned_count=len(followers_list),
                users=followers_list,
            )
        except Exception as e:
            self._handle_error(e, username)
    
    def get_following(self, username: str, max_count: int | None = None) -> FollowerListResponse:
        try:
            user_id = self.get_user_id(username)
            user = self.client.user_info(user_id)
            
            if user.is_private:
                raise PrivateProfileError(username)
            
            following = self.client.user_following(user_id, amount=max_count)
            following_list = []
            
            for pk, user_short in following.items():
                try:
                    entry = FollowerEntry(
                        username=user_short.username,
                        full_name=user_short.full_name or None,
                        is_private=user_short.is_private,
                        is_verified=user_short.is_verified,
                        profile_pic_url=user_short.profile_pic_url,
                    )
                    following_list.append(entry)
                except Exception as e:
                    logger.warning(f"Failed to get following info: {e}")
                    continue
            
            return FollowerListResponse(
                username=username,
                list_type="following",
                total_count=user.following_count,
                returned_count=len(following_list),
                users=following_list,
            )
        except Exception as e:
            self._handle_error(e, username)
    
    def download_post_by_shortcode(self, shortcode: str, target_dir: Path, include_metadata: bool = True) -> dict:
        try:
            media_id = self.client.media_id_from_code(shortcode)
            media = self.client.media_info(media_id)
            
            post_folder = target_dir / f"{datetime.fromtimestamp(media.taken_at).strftime('%Y-%m-%d')}-{shortcode}"
            post_folder.mkdir(parents=True, exist_ok=True)
            
            media_files = []
            if media.media_type == 1:
                path = self.client.photo_download(media_id, filename=str(post_folder / "photo"))
                if path:
                    media_files.append(Path(path))
            elif media.media_type == 2:
                path = self.client.video_download(media_id, filename=str(post_folder / "video"))
                if path:
                    media_files.append(Path(path))
            elif media.media_type == 8:
                for i, resource in enumerate(media.resources):
                    if resource.media_type == 1:
                        path = self.client.photo_download(resource.id, filename=str(post_folder / f"photo_{i}"))
                    else:
                        path = self.client.video_download(resource.id, filename=str(post_folder / f"video_{i}"))
                    if path:
                        media_files.append(Path(path))
            
            metadata = PostMetadata(
                shortcode=shortcode,
                post_date=datetime.fromtimestamp(media.taken_at),
                caption=media.caption_text if hasattr(media, 'caption_text') else None,
                hashtags=re.findall(r'#(\w+)', media.caption_text) if hasattr(media, 'caption_text') and media.caption_text else [],
                likes=media.like_count if hasattr(media, 'like_count') else 0,
                comments=media.comment_count if hasattr(media, 'comment_count') else 0,
                is_video=media.media_type == 2,
                video_view_count=media.view_count if hasattr(media, 'view_count') else None,
                location=media.location.name if hasattr(media, 'location') and media.location else None,
            )
            
            if include_metadata:
                self._save_metadata(metadata, post_folder / "metadata.txt")
            
            return {
                "shortcode": shortcode,
                "owner": media.user.username if hasattr(media, 'user') else "",
                "media_files": media_files,
                "post_folder": post_folder,
                "metadata": metadata,
                "is_sidecar": media.media_type == 8,
                "mediacount": len(media.resources) if media.media_type == 8 else 1,
            }
        except Exception as e:
            self._handle_error(e)
