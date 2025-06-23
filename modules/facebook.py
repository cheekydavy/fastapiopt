from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import yt_dlp
import uuid
import logging
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

async def get_facebook_info_and_url(url: str) -> tuple[str, str, str]:
    """Get Facebook info and direct URL using JSON output"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--quiet",
        "--no-warnings",
        "-f", "best",
        url
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if stderr and "ERROR" in stderr.decode():
        logger.error(f"Facebook yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail="Failed to get Facebook info")
    
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No Facebook info received")
    
    try:
        info = json.loads(stdout.decode())
        
        direct_url = info.get('url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid Facebook URL found")
        
        title = info.get('title', 'facebook_video')
        ext = info.get('ext', 'mp4')
        
        logger.info(f"Got Facebook direct URL: {direct_url[:100]}...")
        
        return direct_url, title, ext
        
    except json.JSONDecodeError as e:
        logger.error(f"Facebook JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse Facebook info")

async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with 2MB chunks and proper encoding"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Referer': 'https://www.facebook.com/'
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    
    # Ensure URL is properly encoded
    try:
        # Parse and reconstruct URL to handle encoding issues
        from urllib.parse import urlparse, urlunparse, quote
        parsed = urlparse(url)
        # Re-encode the path and query to handle special characters
        safe_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            quote(parsed.path.encode('utf-8'), safe='/'),
            parsed.params,
            quote(parsed.query.encode('utf-8'), safe='&='),
            parsed.fragment
        ))
    except Exception as e:
        logger.warning(f"URL encoding issue, using original: {e}")
        safe_url = url
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(safe_url, allow_redirects=True) as response:
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch Facebook media: HTTP {response.status}")
                
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
                    
        except aiohttp.ClientError as e:
            logger.error(f"Facebook streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")
        except UnicodeEncodeError as e:
            logger.error(f"Facebook URL encoding error: {e}")
            raise HTTPException(status_code=500, detail="URL contains invalid characters")

# ORIGINAL ENDPOINT (KEEP AS-IS)
@router.get("/api/fburl")
async def download_facebook_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Facebook URL")
):
    """Download Facebook video - Original endpoint"""
    if not ("facebook.com" in url or "fb.watch" in url):
        raise HTTPException(status_code=400, detail="Invalid Facebook URL")
    
    try:
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.mp4"
        output_path = temp_dir / filename
        
        ydl_opts = {
            'outtmpl': str(output_path),
            'format': 'best',
            'no_cache_dir': True,
            'quiet': True,
        }
        
        loop = asyncio.get_event_loop()
        
        def download_video():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info
        
        info = await loop.run_in_executor(None, download_video)
        
        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Download failed - file not found")
        
        title = info.get('title', 'facebook_video')
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp4",
            media_type="video/mp4"
        )
        
    except Exception as e:
        logger.error(f"Facebook download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# NEW STREAMING ENDPOINT (FOR WEBSITE)
@router.get("/stream/fburl")
async def stream_facebook_video(
    url: str = Query(..., description="Facebook URL")
):
    """Stream Facebook video with browser progress"""
    if not ("facebook.com" in url or "fb.watch" in url):
        raise HTTPException(status_code=400, detail="Invalid Facebook URL")
    
    try:
        # Get direct URL and info
        direct_url, title, ext = await get_facebook_info_and_url(url)
        
        return StreamingResponse(
            stream_from_url(direct_url, chunk_size=2097152),  # 2MB chunks
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes"
            }
        )
        
    except Exception as e:
        logger.error(f"Facebook stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")
