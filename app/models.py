"""Pydantic models for request/response schemas."""

from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class ContentType(str, Enum):
    """Types of content that can be downloaded."""
    ALL = "all"
    POSTS = "posts"
    STORIES = "stories"
    PROFILE_PIC = "profile_pic"


class ErrorResponse(BaseModel):
    """Error response model."""
    success: bool = False
    error: str
    error_code: str
    timestamp: datetime = Field(default_factory=datetime.now)
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "Instagram user not found: 'invalid_user'",
                "error_code": "USER_NOT_FOUND",
                "timestamp": "2024-01-15T10:30:00"
            }
        }


class DownloadRequest(BaseModel):
    """Request model for download endpoints."""
    username: str = Field(
        ..., 
        min_length=1, 
        max_length=30,
        description="Instagram username",
        json_schema_extra={"example": "instagram"}
    )
    include_metadata: bool = Field(
        default=True,
        description="Include metadata files"
    )
    max_posts: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of posts (None = all)"
    )


class ProfileInfo(BaseModel):
    """Basic profile information."""
    username: str
    full_name: str | None
    biography: str | None
    followers: int
    following: int
    post_count: int
    is_private: bool
    is_verified: bool
    profile_pic_url: str | None
    external_url: str | None


class PostMetadata(BaseModel):
    """Metadata for a single post."""
    shortcode: str
    post_date: datetime
    caption: str | None
    hashtags: list[str]
    likes: int
    comments: int
    is_video: bool
    video_view_count: int | None
    location: str | None


class DownloadStats(BaseModel):
    """Statistics about the download."""
    username: str
    content_type: ContentType
    total_posts: int = 0
    total_stories: int = 0
    profile_pic_included: bool = False
    total_files: int = 0
    zip_size_bytes: int = 0
    download_time_seconds: float = 0


class SuccessResponse(BaseModel):
    """Success response model (for non-file responses)."""
    success: bool = True
    message: str
    data: dict | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str
    timestamp: datetime = Field(default_factory=datetime.now)
