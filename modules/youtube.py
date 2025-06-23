from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import asyncio
import subprocess
import os
import re
import json
import logging
from pathlib import Path
import time
from typing import Optional, AsyncGenerator
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

async def get_video_info(url: str, cookies_file: Optional[Path] = None) -> dict:
    """Get video metadata using yt-dlp"""
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    
    cmd = f'yt-dlp --dump-json {cookies_option} "{url}"'
    
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if stderr and "ERROR" in stderr.decode():
        raise HTTPException(status_code=500, detail=f"Failed to get video info: {stderr.decode()}")
    
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No video information received")
    
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse video information")

async def stream_download(url: str, format_selector: str, cookies_file: Optional[Path] = None) -> AsyncGenerator[bytes, None]:
    """Stream download using yt-dlp subprocess"""
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    
    # Use yt-dlp to stream directly to stdout
    cmd = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "-f", format_selector,
        "-o", "-",  # Output to stdout
        url
    ]
    
    if cookies_file:
        cmd.extend(["--cookies", str(cookies_file)])
    
    logger.info(f"Starting stream download with command: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    try:
        # Stream data in chunks
        while True:
            chunk = await process.stdout.read(8192)  # 8KB chunks
            if not chunk:
                break
            yield chunk
        
        # Wait for process to complete
        await process.wait()
        
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            logger.error(f"yt-dlp error: {stderr_output.decode()}")
            raise HTTPException(status_code=500, detail="Download failed")
            
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        if process.returncode is None:
            process.terminate()
            await process.wait()
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")

@router.get("/download/audio")
async def download_youtube_audio(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality (128K, 192K, 320K)")
):
    """Stream YouTube audio download"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_qualities else '192K'
    
    cookies_file = get_cookies_file()
    
    try:
        # Get video info for filename
        video_info = await get_video_info(song, cookies_file)
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info.get('title', 'unknown'))
        
        # Format selector for audio
        format_selector = f"bestaudio[abr<={audio_quality[:-1]}]/bestaudio/best"
        
        # Create streaming response
        return StreamingResponse(
            stream_download(song, format_selector, cookies_file),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{video_title}_{audio_quality}.mp3"',
                "Cache-Control": "no-cache",
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
    """Stream YouTube video download"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_qualities else '720p'
    
    cookies_file = get_cookies_file()
    
    try:
        # Get video info for filename
        video_info = await get_video_info(song, cookies_file)
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info.get('title', 'unknown'))
        
        # Quality format mapping for streaming
        quality_formats = {
            '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
            '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
            '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        }
        
        format_selector = quality_formats.get(video_quality, 'bestvideo[height<=720]+bestaudio/best')
        
        # Create streaming response
        return StreamingResponse(
            stream_download(song, format_selector, cookies_file),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{video_title}_{video_quality}.mp4"',
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
