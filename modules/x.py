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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cleanup_file(file_path: Path):
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup {file_path}: {e}")


async def get_x_info_and_url(url: str) -> tuple[str, str, str]:
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
        logger.error(f"X yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail="Failed to get X info")
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No X info received")

    try:
        info = json.loads(stdout.decode())
        direct_url = info.get('url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid X URL found")
        title = info.get('title', 'x_video')
        ext = info.get('ext', 'mp4')
        logger.info(f"Got X direct URL: {direct_url[:100]}...")
        return direct_url, title, ext
    except json.JSONDecodeError as e:
        logger.error(f"X JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse X info")


async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Referer': 'https://x.com/',
        'Origin': 'https://x.com',
        'Sec-Fetch-Dest': 'video',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site'
    }
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch X media: HTTP {response.status}")
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
        except aiohttp.ClientError as e:
            logger.error(f"X streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")


@router.get("/api/xurl")
async def download_x_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="X/Twitter URL")
):
    if not ("x.com" in url or "twitter.com" in url):
        raise HTTPException(status_code=400, detail="Invalid X/Twitter URL")

    try:
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
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

        title = info.get('title', 'x_video')
        background_tasks.add_task(cleanup_file, output_path)

        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp4",
            media_type="video/mp4"
        )

    except Exception as e:
        logger.error(f"X/Twitter download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.get("/stream/xurl")
async def stream_x_video(
    url: str = Query(..., description="X/Twitter URL")
):
    if not ("x.com" in url or "twitter.com" in url):
        raise HTTPException(status_code=400, detail="Invalid X/Twitter URL")

    try:
        direct_url, title, ext = await get_x_info_and_url(url)

        return StreamingResponse(
            stream_from_url(direct_url, chunk_size=2097152),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes"
            }
        )

    except Exception as e:
        logger.error(f"X stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")
