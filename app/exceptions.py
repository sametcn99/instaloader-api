"""Custom exceptions for the Instaloader API."""

__all__ = [
    "InstagramDownloaderError",
    "UserNotFoundError",
    "PrivateProfileError",
    "ProfileSuspendedError",
    "RateLimitError",
    "LoginRequiredError",
    "DownloadError",
    "NoContentError",
    "TimeoutError",
]


class InstagramDownloaderError(Exception):
    """Base exception for Instagram Downloader."""
    
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class UserNotFoundError(InstagramDownloaderError):
    """Raised when Instagram user is not found."""
    
    def __init__(self, username: str):
        super().__init__(
            message=f"Instagram user not found: '{username}'",
            status_code=404
        )


class PrivateProfileError(InstagramDownloaderError):
    """Raised when trying to access a private profile without authentication."""
    
    def __init__(self, username: str):
        super().__init__(
            message=f"'{username}' profile is private. You need to log in to access this content.",
            status_code=403
        )


class ProfileSuspendedError(InstagramDownloaderError):
    """Raised when the profile is suspended."""
    
    def __init__(self, username: str):
        super().__init__(
            message=f"'{username}' account has been suspended or removed.",
            status_code=410
        )


class RateLimitError(InstagramDownloaderError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self):
        super().__init__(
            message="Instagram API rate limit exceeded. Please wait a while and try again.",
            status_code=429
        )


class LoginRequiredError(InstagramDownloaderError):
    """Raised when login is required for an operation."""
    
    def __init__(self, operation: str = "this operation"):
        super().__init__(
            message=f"You need to log in to Instagram for '{operation}'.",
            status_code=401
        )


class DownloadError(InstagramDownloaderError):
    """Raised when download fails."""
    
    def __init__(self, message: str = "Download operation failed."):
        super().__init__(
            message=message,
            status_code=500
        )


class NoContentError(InstagramDownloaderError):
    """Raised when no content is available to download."""
    
    def __init__(self, content_type: str = "content"):
        super().__init__(
            message=f"No {content_type} found to download.",
            status_code=404
        )


class TimeoutError(InstagramDownloaderError):
    """Raised when operation times out."""
    
    def __init__(self):
        super().__init__(
            message="Operation timed out. Please try again.",
            status_code=504
        )
