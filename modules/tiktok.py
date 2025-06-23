from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import asyncio
import urllib.parse
import logging
import re
from typing import AsyncGenerator, Optional
import json

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sanitize_filename(value: str) -> str:
    """Sanitize filename to remove invalid characters"""
    if not value:
        return "Unknown_Title"
    sanitized = re.sub(r'[^\w\s-]', '', value)
    sanitized = re.sub(r'\s+', '_', sanitized).strip()
    return sanitized or "Unknown_Title"

async def get_tiktok_info(url: str) -> tuple[str, str]:
    """Get TikTok video info"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--quiet",
        "--no-warnings",
        url
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    try:
        if stdout:
            info = json.loads(stdout.decode())
            thumbnail = info.get('thumbnail', '')
            title = sanitize_filename(info.get('title', 'Unknown Title'))
            return thumbnail, title
    except Exception as e:
        logger.error(f"Failed to extract TikTok info: {e}")
    
    return '', 'Unknown_Title'

async def stream_tiktok_download(url: str, format_selector: str) -> AsyncGenerator[bytes, None]:
    """Stream TikTok download"""
    cmd = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "--retries", "3",
        "-f", format_selector,
        "-o", "-",  # Output to stdout
        url
    ]
    
    logger.info(f"Starting TikTok stream download: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    try:
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                break
            yield chunk
        
        await process.wait()
        
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            logger.error(f"TikTok download error: {stderr_output.decode()}")
            raise HTTPException(status_code=500, detail="TikTok download failed")
            
    except Exception as e:
        logger.error(f"TikTok streaming error: {e}")
        if process.returncode is None:
            process.terminate()
            await process.wait()
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")

@router.get("/api/tiktokurl")
async def download_tiktok_video(
    url: str = Query(..., description="TikTok URL")
):
    """Stream TikTok video download"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok video URL: {decoded_url}")
        
        # Get video info
        thumbnail, title = await get_tiktok_info(decoded_url)
        
        # Stream the download
        return StreamingResponse(
            stream_tiktok_download(decoded_url, "bestvideo+bestaudio/best"),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "x-tiktok-thumbnail": thumbnail or "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg",
                "x-tiktok-title": title,
                "Cache-Control": "no-cache"
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("/api/tiktoaudio")
async def download_tiktok_audio(
    url: str = Query(..., description="TikTok URL")
):
    """Stream TikTok audio download"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok audio URL: {decoded_url}")
        
        # Get video info
        thumbnail, title = await get_tiktok_info(decoded_url)
        
        # Stream the audio download
        return StreamingResponse(
            stream_tiktok_download(decoded_url, "bestaudio/best"),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp3"',
                "x-tiktok-thumbnail": thumbnail or "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg",
                "x-tiktok-title": title,
                "Cache-Control": "no-cache"
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
