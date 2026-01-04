"""Main FastAPI application."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes.download import router as download_router
from app.exceptions import InstagramDownloaderError
from app.models import HealthResponse, ErrorResponse

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Download directory: {settings.DOWNLOAD_DIR}")
    yield
    logger.info("Shutting down application")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "FastAPI wrapper around Instaloader. Source code and issue tracker on "
        "[GitHub](https://github.com/sametcn99/instaloader-api)."
    ),
    contact={
        "name": "sametcc.me",
        "url": "https://sametcc.me",
    },
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(InstagramDownloaderError)
async def instagram_exception_handler(request: Request, exc: InstagramDownloaderError):
    """Handle Instagram-specific exceptions."""
    error_codes = {
        404: "USER_NOT_FOUND",
        403: "PRIVATE_PROFILE",
        429: "RATE_LIMITED",
        410: "PROFILE_SUSPENDED",
        500: "DOWNLOAD_ERROR",
        504: "TIMEOUT",
    }
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.message,
            "error_code": error_codes.get(exc.status_code, "UNKNOWN_ERROR"),
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.exception("Unexpected error")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "An unexpected error occurred.",
            "error_code": "INTERNAL_ERROR",
            "timestamp": datetime.now().isoformat(),
        }
    )


# Health check endpoint
@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check"
)
async def health_check():
    """Check if the API is running."""
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        timestamp=datetime.now()
    )


# Include routers
app.include_router(download_router)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Root endpoint - serve index.html
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Serve the main UI page."""
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_file.read_text(), status_code=200)


def start():
    """Start the application with uvicorn."""
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )


if __name__ == "__main__":
    start()
