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

async def get_facebook_info(url: str) -> str:
    """Get Facebook video info"""
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
            return info.get('title', 'facebook_video')
    except Exception as e:
        logger.error(f"Failed to extract Facebook info: {e}")
    
    return 'facebook_video'

async def stream_facebook_download(url: str) -> AsyncGenerator[bytes, None]:
    """Stream Facebook download"""
    cmd = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "-f", "best",
        "-o", "-",
        url
    ]
    
    logger.info(f"Starting Facebook stream download")
    
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
            logger.error(f"Facebook download error: {stderr_output.decode()}")
            raise HTTPException(status_code=500, detail="Facebook download failed")
            
    except Exception as e:
        logger.error(f"Facebook streaming error: {e}")
        if process.returncode is None:
            process.terminate()
            await process.wait()
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")

@router.get("/api/fburl")
async def download_facebook_video(
    url: str = Query(..., description="Facebook URL")
):
    """Stream Facebook video download"""
    if not ("facebook.com" in url or "fb.watch" in url):
        raise HTTPException(status_code=400, detail="Invalid Facebook URL")
    
    try:
        # Get video info
        title = await get_facebook_info(url)
        
        return StreamingResponse(
            stream_facebook_download(url),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Cache-Control": "no-cache"
            }
        )
        
    except Exception as e:
        logger.error(f"Facebook download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
