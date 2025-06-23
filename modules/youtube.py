from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, RedirectResponse
import asyncio
import subprocess
import os
import re
import json
import logging
from pathlib import Path
import time
from typing import Optional, AsyncGenerator
import aiohttp
import tempfile

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_cookies_file() -> Path:
    """Find cookies file in various possible locations"""
    possible_paths = [
        Path('cookies.txt'),
        Path('/app/cookies.txt'),
        Path('modules/cookies.txt'),
        Path('/app/modules/cookies.txt'),
        Path(os.getcwd()) / 'cookies.txt',
    ]
    
    for path in possible_paths:
        if path.exists():
            logger.info(f"Found cookies file at: {path}")
            return path
    
    logger.warning("No cookies file found")
    return None

def is_valid_youtube_url(url: str) -> bool:
    """Validate YouTube URL"""
    pattern = r'^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$'
    return bool(re.match(pattern, url))

async def get_direct_url(url: str, format_selector: str, cookies_file: Optional[Path] = None) -> tuple[str, str, str]:
    """Get direct download URL using yt-dlp without downloading"""
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    
    # Get both the direct URL and metadata
    cmd = f'yt-dlp --get-url --get-title --get-filename -f "{format_selector}" {cookies_option} "{url}"'
    
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if stderr and "ERROR" in stderr.decode():
        logger.error(f"yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail=f"Failed to get download URL: {stderr.decode()}")
    
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No download URL received")
    
    lines = stdout.decode().strip().split('\n')
    if len(lines) < 3:
        raise HTTPException(status_code=500, detail="Invalid response from yt-dlp")
    
    direct_url = lines[0]
    title = lines[1]
    filename = lines[2]
    
    return direct_url, title, filename

async def stream_from_url(url: str, filename: str) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with proper headers"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise HTTPException(status_code=500, detail=f"Failed to fetch media: HTTP {response.status}")
            
            # Stream the content in chunks
            async for chunk in response.content.iter_chunked(8192):
                yield chunk

@router.get("/download/audio")
async def download_youtube_audio(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality (128K, 192K, 320K)")
):
    """Direct stream YouTube audio - shows browser download progress"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_qualities else '192K'
    
    cookies_file = get_cookies_file()
    
    try:
        # Format selector for audio
        format_selector = f"bestaudio[abr<={audio_quality[:-1]}]/bestaudio/best"
        
        # Get direct URL without downloading
        direct_url, title, filename = await get_direct_url(song, format_selector, cookies_file)
        
        logger.info(f"Got direct URL for {title}: {direct_url[:100]}...")
        
        # Clean filename
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
        
        # Stream directly from the URL
        return StreamingResponse(
            stream_from_url(direct_url, filename),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}_{audio_quality}.mp3"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "X-Content-Type-Options": "nosniff"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("/download/video")
async def download_youtube_video(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("720p", description="Video quality (144p, 240p, 360p, 480p, 720p, 1080p)")
):
    """Direct stream YouTube video - shows browser download progress"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_qualities else '720p'
    
    cookies_file = get_cookies_file()
    
    try:
        # Quality format mapping
        quality_formats = {
            '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
            '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
            '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        }
        
        format_selector = quality_formats.get(video_quality, 'bestvideo[height<=720]+bestaudio/best')
        
        # Get direct URL without downloading
        direct_url, title, filename = await get_direct_url(song, format_selector, cookies_file)
        
        logger.info(f"Got direct URL for {title}: {direct_url[:100]}...")
        
        # Clean filename
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
        
        # Stream directly from the URL
        return StreamingResponse(
            stream_from_url(direct_url, filename),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}_{video_quality}.mp4"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "X-Content-Type-Options": "nosniff"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# Alternative approach using redirect (even faster)
@router.get("/download/audio/redirect")
async def download_youtube_audio_redirect(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality")
):
    """Redirect directly to YouTube audio URL - fastest method"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    cookies_file = get_cookies_file()
    format_selector = f"bestaudio[abr<={quality[:-1] if quality else '192'}]/bestaudio/best"
    
    try:
        direct_url, title, filename = await get_direct_url(song, format_selector, cookies_file)
        
        # Direct redirect - browser handles the download with progress
        return RedirectResponse(url=direct_url, status_code=302)
        
    except Exception as e:
        logger.error(f"YouTube audio redirect error: {e}")
        raise HTTPException(status_code=500, detail=f"Redirect failed: {str(e)}")

@router.get("/download/video/redirect")
async def download_youtube_video_redirect(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("720p", description="Video quality")
):
    """Redirect directly to YouTube video URL - fastest method"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    cookies_file = get_cookies_file()
    
    quality_formats = {
        '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
        '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
        '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
        '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
        '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    }
    
    format_selector = quality_formats.get(quality, 'bestvideo[height<=720]+bestaudio/best')
    
    try:
        direct_url, title, filename = await get_direct_url(song, format_selector, cookies_file)
        
        # Direct redirect - browser handles the download with progress
        return RedirectResponse(url=direct_url, status_code=302)
        
    except Exception as e:
        logger.error(f"YouTube video redirect error: {e}")
        raise HTTPException(status_code=500, detail=f"Redirect failed: {str(e)}")
