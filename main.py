from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from pathlib import Path

from modules.youtube import router as youtube_router
from modules.tiktok import router as tiktok_router
from modules.instagram import router as instagram_router
from modules.facebook import router as facebook_router
from modules.x import router as x_router

app = FastAPI(
    title="Media Downloader API - Hybrid Edition",
    description="High-performance media downloader with both traditional and streaming endpoints supporting YouTube, TikTok, Instagram, Facebook, and X/Twitter",
    version="3.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods including OPTIONS
    allow_headers=["*"],  # Allows all headers
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers with original endpoint structure
app.include_router(youtube_router, tags=["YouTube"])
app.include_router(tiktok_router, tags=["TikTok"])  
app.include_router(instagram_router, tags=["Instagram"])
app.include_router(facebook_router, tags=["Facebook"])
app.include_router(x_router, tags=["X/Twitter"])

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main frontend page"""
    static_path = Path("static/index.html")
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text(), status_code=200)
    return HTMLResponse("""
    <html>
        <head><title>Media Downloader - Hybrid Edition</title></head>
        <body>
            <h1>Media Downloader API - Hybrid Edition</h1>
            <p>Now with both traditional and streaming endpoints!</p>
            <h3>Traditional Endpoints (File-based):</h3>
            <ul>
                <li>/download/audio - Download YouTube audio</li>
                <li>/download/video - Download YouTube video</li>
                <li>/api/tiktokurl - Download TikTok video</li>
                <li>/api/tiktoaudio - Download TikTok audio</li>
                <li>/download/iglink - Download Instagram media</li>
                <li>/api/fburl - Download Facebook video</li>
                <li>/api/xurl - Download X/Twitter video</li>
            </ul>
            <h3>Streaming Endpoints (Fast):</h3>
            <ul>
                <li>/stream/audio - Stream YouTube audio</li>
                <li>/stream/video - Stream YouTube video</li>
                <li>/stream/tiktokurl - Stream TikTok video</li>
                <li>/stream/tiktoaudio - Stream TikTok audio</li>
                <li>/stream/iglink - Stream Instagram media</li>
                <li>/stream/fburl - Stream Facebook video</li>
                <li>/stream/xurl - Stream X/Twitter video</li>
            </ul>
            <p><a href="/docs">API Documentation</a></p>
        </body>
    </html>
    """)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok", 
        "message": "Media Downloader API is running - Hybrid Edition",
        "version": "3.0.0",
        "features": ["traditional_downloads", "streaming_downloads", "browser_progress"],
        "services": {
            "main_api": "running",
            "streaming_api": "running"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        workers=1,
        loop="uvloop"
    )
