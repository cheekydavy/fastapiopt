from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import os
import uuid
import urllib.parse
import logging
import re
from pathlib import Path
from typing import AsyncGenerator
import aiohttp
import requests

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TIKWM_API = "https://www.tikwm.com/api/"
TIKWM_HEADERS = {
    "User-Agent": "ToxicAPIs/2.0",
    "Referer": "https://www.tikwm.com/"
}
FALLBACK_THUMB = "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg"

VALID_TIKTOK_PREFIXES = (
    "https://www.tiktok.com/",
    "https://vt.tiktok.com",
    "https://vm.tiktok.com/",
    "http://www.tiktok.com/",
    "http://vt.tiktok.com",
    "http://vm.tiktok.com/",
)

SHORT_TIKTOK_HOSTS = ("vm.tiktok", "vt.tiktok", "m.tiktok")


def sanitize_filename(value: str) -> str:
    if not value:
        return "Unknown_Title"
    sanitized = re.sub(r'[^\w\s-]', '', value)
    sanitized = re.sub(r'\s+', '_', sanitized).strip()
    return sanitized or "Unknown_Title"


def resolve_short_url(url: str) -> str:
    if not any(h in url for h in SHORT_TIKTOK_HOSTS):
        return url
    try:
        r = requests.get(
            url,
            allow_redirects=True,
            timeout=10,
            headers={"User-Agent": "TikTok 26.2.0 rv:262018 (iPhone; iOS 14.4.2; en_US) Cronet"}
        )
        resolved = r.url
        if resolved and "tiktok.com" in resolved:
            return resolved
    except Exception as e:
        logger.warning(f"Short URL resolution failed: {e}")
    return url


def fetch_tikwm(url: str) -> dict:
    resolved = resolve_short_url(url)
    params = {"url": resolved, "hd": "1"}
    r = requests.get(TIKWM_API, params=params, headers=TIKWM_HEADERS, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") == 0 and j.get("data"):
        return j["data"]
    raise ValueError(j.get("msg") or "TikWM API returned no data")


def cleanup_file(file_path: Path):
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup {file_path}: {e}")


def validate_tiktok_url(url: str) -> str:
    decoded = urllib.parse.unquote(url)
    if not any(decoded.startswith(p) for p in VALID_TIKTOK_PREFIXES):
        raise HTTPException(status_code=400, detail="URL must be a valid TikTok link.")
    return decoded


async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": "https://www.tiktok.com/",
        "Origin": "https://www.tiktok.com",
    }
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=502, detail=f"TikWM media returned HTTP {response.status}")
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
        except aiohttp.ClientError as e:
            logger.error(f"TikTok streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")


@router.get("/api/tiktokurl")
async def download_tiktok_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="TikTok URL")
):
    tiktok_url = validate_tiktok_url(url)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: fetch_tikwm(tiktok_url))
    except Exception as e:
        logger.error(f"TikWM fetch error: {e}")
        raise HTTPException(status_code=502, detail=f"Could not fetch TikTok video: {e}")

    title = sanitize_filename(data.get("title", "tiktok_video"))
    thumbnail = data.get("cover") or FALLBACK_THUMB
    video_url = data.get("hdplay") or data.get("play")

    if not video_url:
        raise HTTPException(status_code=502, detail="No video URL returned by TikWM")

    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    local_path = temp_dir / f"{uuid.uuid4()}.mp4"

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: __import__("urllib.request", fromlist=["urlretrieve"]).urlretrieve(video_url, str(local_path)))
    except Exception as e:
        logger.error(f"Video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download video: {e}")

    background_tasks.add_task(cleanup_file, local_path)

    return FileResponse(
        path=str(local_path),
        filename=f"{title}.mp4",
        media_type="video/mp4",
        headers={
            "x-tiktok-thumbnail": thumbnail,
            "x-tiktok-title": title,
        }
    )


@router.get("/api/tiktoaudio")
async def download_tiktok_audio(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="TikTok URL")
):
    tiktok_url = validate_tiktok_url(url)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: fetch_tikwm(tiktok_url))
    except Exception as e:
        logger.error(f"TikWM fetch error: {e}")
        raise HTTPException(status_code=502, detail=f"Could not fetch TikTok audio: {e}")

    title = sanitize_filename(data.get("title", "tiktok_audio"))
    thumbnail = data.get("cover") or FALLBACK_THUMB
    music_url = data.get("music")

    if not music_url:
        raise HTTPException(status_code=502, detail="No audio URL returned by TikWM")

    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    local_path = temp_dir / f"{uuid.uuid4()}.mp3"

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: __import__("urllib.request", fromlist=["urlretrieve"]).urlretrieve(music_url, str(local_path)))
    except Exception as e:
        logger.error(f"Audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download audio: {e}")

    background_tasks.add_task(cleanup_file, local_path)

    return FileResponse(
        path=str(local_path),
        filename=f"{title}.mp3",
        media_type="audio/mpeg",
        headers={
            "x-tiktok-thumbnail": thumbnail,
            "x-tiktok-title": title,
        }
    )


@router.get("/stream/tiktokurl")
async def stream_tiktok_video(
    url: str = Query(..., description="TikTok URL")
):
    tiktok_url = validate_tiktok_url(url)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: fetch_tikwm(tiktok_url))
    except Exception as e:
        logger.error(f"TikWM fetch error: {e}")
        raise HTTPException(status_code=502, detail=f"Could not fetch TikTok video: {e}")

    title = sanitize_filename(data.get("title", "tiktok_video"))
    video_url = data.get("hdplay") or data.get("play")

    if not video_url:
        raise HTTPException(status_code=502, detail="No video URL returned by TikWM")

    return StreamingResponse(
        stream_from_url(video_url),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{title}.mp4"',
            "Cache-Control": "no-cache",
            "Accept-Ranges": "bytes",
            "x-tiktok-title": title,
        }
    )


@router.get("/stream/tiktoaudio")
async def stream_tiktok_audio(
    url: str = Query(..., description="TikTok URL")
):
    tiktok_url = validate_tiktok_url(url)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: fetch_tikwm(tiktok_url))
    except Exception as e:
        logger.error(f"TikWM fetch error: {e}")
        raise HTTPException(status_code=502, detail=f"Could not fetch TikTok audio: {e}")

    title = sanitize_filename(data.get("title", "tiktok_audio"))
    music_url = data.get("music")

    if not music_url:
        raise HTTPException(status_code=502, detail="No audio URL returned by TikWM")

    return StreamingResponse(
        stream_from_url(music_url),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{title}.mp3"',
            "Cache-Control": "no-cache",
            "Accept-Ranges": "bytes",
            "x-tiktok-title": title,
        }
    )
