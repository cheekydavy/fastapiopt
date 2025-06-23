from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
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
    title="Media Downloader API - Streaming Edition",
    description="High-performance streaming media downloader supporting YouTube, TikTok, Instagram, Facebook, and X/Twitter",
    version="3.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
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
        <head><title>Streaming Media Downloader</title></head>
        <body>
            <h1>Streaming Media Downloader API</h1>
            <p>Now with streaming downloads for faster performance!</p>
            <ul>
                <li>/download/audio - Stream YouTube audio</li>
                <li>/download/video - Stream YouTube video</li>
                <li>/api/tiktokurl - Stream TikTok video</li>
                <li>/api/tiktoaudio - Stream TikTok audio</li>
                <li>/download/iglink - Stream Instagram media</li>
                <li>/api/fburl - Stream Facebook video</li>
                <li>/api/xurl - Stream X/Twitter video</li>
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
        "message": "Streaming Media Downloader API is running",
        "version": "3.0.0",
        "features": ["streaming_downloads", "no_temp_files", "faster_response"]
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        workers=1,
        loop="uvloop"
    )
