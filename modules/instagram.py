from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import asyncio
import logging
from typing import AsyncGenerator
import json

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_instagram_info(url: str) -> tuple[str, str]:
    """Get Instagram media info"""
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
            title = info.get('title', 'instagram_media')
            ext = info.get('ext', 'mp4')
            return title, ext
    except Exception as e:
        logger.error(f"Failed to extract Instagram info: {e}")
    
    return 'instagram_media', 'mp4'

async def stream_instagram_download(url: str) -> AsyncGenerator[bytes, None]:
    """Stream Instagram download"""
    cmd = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "-f", "best",
        "-o", "-",
        url
    ]
    
    logger.info(f"Starting Instagram stream download")
    
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
            logger.error(f"Instagram download error: {stderr_output.decode()}")
            raise HTTPException(status_code=500, detail="Instagram download failed")
            
    except Exception as e:
        logger.error(f"Instagram streaming error: {e}")
        if process.returncode is None:
            process.terminate()
            await process.wait()
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")

@router.get("/download/iglink")
async def download_instagram_media(
    url: str = Query(..., description="Instagram URL")
):
    """Stream Instagram media download"""
    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        raise HTTPException(status_code=400, detail="Invalid Instagram URL")
    
    try:
        # Get media info
        title, ext = await get_instagram_info(url)
        
        # Determine media type
        media_type = 'video/mp4' if ext in ['.mp4', '.mov'] else 'image/jpeg'
        
        return StreamingResponse(
            stream_instagram_download(url),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{title}.{ext}"',
                "Cache-Control": "no-cache"
            }
        )
        
    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
