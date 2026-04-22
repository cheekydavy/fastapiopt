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
    title="Media Downloader API",
    description="High-performance media downloader supporting YouTube, TikTok, Instagram, Facebook, and X/Twitter",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(youtube_router, tags=["YouTube"])
app.include_router(tiktok_router, tags=["TikTok"])
app.include_router(instagram_router, tags=["Instagram"])
app.include_router(facebook_router, tags=["Facebook"])
app.include_router(x_router, tags=["X/Twitter"])


@app.get("/", response_class=HTMLResponse)
async def home():
    static_path = Path("static/index.html")
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text(), status_code=200)
    return HTMLResponse("""
    <html>
        <head><title>Media Downloader</title></head>
        <body>
            <h1>Media Downloader API</h1>
            <ul>
                <li>/download/audio - YouTube audio</li>
                <li>/download/video - YouTube video</li>
                <li>/api/tiktokurl - TikTok video</li>
                <li>/api/tiktoaudio - TikTok audio</li>
                <li>/stream/tiktokurl - TikTok video stream</li>
                <li>/stream/tiktoaudio - TikTok audio stream</li>
                <li>/download/iglink - Instagram media</li>
                <li>/api/fburl - Facebook video</li>
                <li>/api/xurl - X/Twitter video</li>
            </ul>
            <p><a href="/docs">API Documentation</a></p>
        </body>
    </html>
    """)


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "3.0.0"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        workers=1,
        loop="uvloop"
    )
