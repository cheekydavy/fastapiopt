from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, RedirectResponse
import asyncio
import urllib.parse
import logging
import re
from typing import AsyncGenerator, Optional
import json
import aiohttp

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

async def get_tiktok_info_and_url(url: str, format_selector: str) -> tuple[str, str, str]:
    """Get TikTok info and direct URL using JSON output"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--quiet",
        "--no-warnings",
        "-f", format_selector,
        url
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if stderr and "ERROR" in stderr.decode():
        logger.error(f"TikTok yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail="Failed to get TikTok info")
    
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No TikTok info received")
    
    try:
        info = json.loads(stdout.decode())
        
        direct_url = info.get('url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid TikTok URL found")
        
        title = sanitize_filename(info.get('title', 'tiktok_video'))
        ext = info.get('ext', 'mp4')
        
        logger.info(f"Got TikTok direct URL: {direct_url[:100]}...")
        
        return direct_url, title, ext
        
    except json.JSONDecodeError as e:
        logger.error(f"TikTok JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse TikTok info")

async def stream_from_url(url: str) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with proper headers"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.tiktok.com/'
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url) as response:
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch TikTok media: HTTP {response.status}")
                
                async for chunk in response.content.iter_chunked(8192):
                    yield chunk
                    
        except aiohttp.ClientError as e:
            logger.error(f"TikTok streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")

@router.get("/api/tiktokurl")
async def download_tiktok_video(
    url: str = Query(..., description="TikTok URL")
):
    """Direct stream TikTok video with browser progress"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok video URL: {decoded_url}")
        
        # Get direct URL and info
        direct_url, title, ext = await get_tiktok_info_and_url(decoded_url, "bestvideo+bestaudio/best")
        
        return StreamingResponse(
            stream_from_url(direct_url),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("/api/tiktoaudio")
async def download_tiktok_audio(
    url: str = Query(..., description="TikTok URL")
):
    """Direct stream TikTok audio with browser progress"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok audio URL: {decoded_url}")
        
        # Get direct URL for audio
        direct_url, title, ext = await get_tiktok_info_and_url(decoded_url, "bestaudio/best")
        
        return StreamingResponse(
            stream_from_url(direct_url),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp3"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
