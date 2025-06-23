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

async def get_x_info(url: str) -> str:
    """Get X/Twitter video info"""
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
            return info.get('title', 'x_video')
    except Exception as e:
        logger.error(f"Failed to extract X info: {e}")
    
    return 'x_video'

async def stream_x_download(url: str) -> AsyncGenerator[bytes, None]:
    """Stream X/Twitter download"""
    cmd = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "-f", "best",
        "-o", "-",
        url
    ]
    
    logger.info(f"Starting X/Twitter stream download")
    
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
            logger.error(f"X download error: {stderr_output.decode()}")
            raise HTTPException(status_code=500, detail="X download failed")
            
    except Exception as e:
        logger.error(f"X streaming error: {e}")
        if process.returncode is None:
            process.terminate()
            await process.wait()
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")

@router.get("/api/xurl")
async def download_x_video(
    url: str = Query(..., description="X/Twitter URL")
):
    """Stream X/Twitter video download"""
    if not ("x.com" in url or "twitter.com" in url):
        raise HTTPException(status_code=400, detail="Invalid X/Twitter URL")
    
    try:
        # Get video info
        title = await get_x_info(url)
        
        return StreamingResponse(
            stream_x_download(url),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Cache-Control": "no-cache"
            }
        )
        
    except Exception as e:
        logger.error(f"X/Twitter download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
