from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import os
import uuid
import urllib.parse
import logging
import yt_dlp
import re
from pathlib import Path
from typing import AsyncGenerator
import json
import aiohttp

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_file(file_path: Path):
    """Background task to cleanup temporary files"""
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup {file_path}: {e}")

def sanitize_filename(value: str) -> str:
    """Sanitize filename to remove invalid characters"""
    if not value:
        return "Unknown_Title"
    sanitized = re.sub(r'[^\w\s-]', '', value)
    sanitized = re.sub(r'\s+', '_', sanitized).strip()
    return sanitized or "Unknown_Title"

async def extract_tiktok_info(url: str) -> tuple[str, str]:
    """Extract video info using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
    }
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            thumbnail = info.get('thumbnail', '')
            title = sanitize_filename(info.get('title', 'Unknown Title'))
            return thumbnail, title
    except Exception as e:
        logger.error(f"Failed to extract TikTok info: {e}")
        return '', 'Unknown_Title'

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

async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with 2MB chunks and better error handling"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Referer': 'https://www.tiktok.com/',
        'Origin': 'https://www.tiktok.com',
        'Sec-Fetch-Dest': 'video',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site'
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status == 403:
                    # Try with different headers for 403 errors
                    headers['User-Agent'] = 'TikTok 26.2.0 rv:262018 (iPhone; iOS 14.4.2; en_US) Cronet'
                    headers['Accept'] = 'video/mp4,video/*;q=0.9,*/*;q=0.8'
                    
                    async with session.get(url, headers=headers, allow_redirects=True) as retry_response:
                        if retry_response.status not in [200, 206]:
                            raise HTTPException(status_code=500, detail=f"TikTok media blocked: HTTP {retry_response.status}")
                        
                        async for chunk in retry_response.content.iter_chunked(chunk_size):
                            yield chunk
                        return
                
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch TikTok media: HTTP {response.status}")
                
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
                    
        except aiohttp.ClientError as e:
            logger.error(f"TikTok streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")

async def run_command(command: list) -> tuple[int, str]:
    """Run command asynchronously"""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stderr.decode()

# ORIGINAL ENDPOINTS (KEEP AS-IS)
@router.get("/api/tiktokurl")
async def download_tiktok_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="TikTok URL")
):
    """Download TikTok video (Original endpoint - file-based)"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok video URL: {decoded_url}")
        
        # Extract video info
        thumbnail, title = await extract_tiktok_info(decoded_url)
        
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.mp4"
        output_path = temp_dir / filename
        
        # Download video
        cmd = [
            "yt-dlp",
            "--retries", "3",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", str(output_path),
            decoded_url
        ]
        
        returncode, stderr = await run_command(cmd)
        
        if returncode != 0 or not output_path.exists():
            logger.error(f"TikTok download failed: {stderr}")
            raise HTTPException(status_code=500, detail="Download failed")
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp4",
            media_type="video/mp4",
            headers={
                "x-tiktok-thumbnail": thumbnail or "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("/api/tiktoaudio")
async def download_tiktok_audio(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="TikTok URL")
):
    """Download TikTok audio (Original endpoint - file-based)"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok audio URL: {decoded_url}")
        
        # Extract video info
        thumbnail, title = await extract_tiktok_info(decoded_url)
        
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.mp3"
        output_path = temp_dir / filename
        
        # Download audio
        cmd = [
            "yt-dlp",
            "--retries", "3",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "-o", str(output_path),
            decoded_url
        ]
        
        returncode, stderr = await run_command(cmd)
        
        if returncode != 0 or not output_path.exists():
            logger.error(f"TikTok audio download failed: {stderr}")
            raise HTTPException(status_code=500, detail="Download failed")
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp3",
            media_type="audio/mpeg",
            headers={
                "x-tiktok-thumbnail": thumbnail or "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# NEW STREAMING ENDPOINTS (FOR WEBSITE)
@router.get("/stream/tiktokurl")
async def stream_tiktok_video(
    url: str = Query(..., description="TikTok URL")
):
    """Stream TikTok video with browser progress"""
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
            stream_from_url(direct_url, chunk_size=2097152),  # 2MB chunks
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok video stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")

@router.get("/stream/tiktoaudio")
async def stream_tiktok_audio(
    url: str = Query(..., description="TikTok URL")
):
    """Stream TikTok audio with browser progress"""
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
            stream_from_url(direct_url, chunk_size=2097152),  # 2MB chunks
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp3"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok audio stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")
