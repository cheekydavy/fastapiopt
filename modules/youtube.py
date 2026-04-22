from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, RedirectResponse
import asyncio
import os
import re
import json
import logging
from pathlib import Path
import time
from typing import Optional, AsyncGenerator
import aiohttp

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_cookies_file() -> Path:
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
    pattern = r'^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$'
    return bool(re.match(pattern, url))


def sanitize_filename(name: str) -> str:
    """Keep the real title but strip filesystem-unsafe characters."""
    # Replace unsafe chars with underscore but preserve spaces, hyphens, dots
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name).strip()
    # Collapse multiple underscores/spaces
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned or "download"


async def get_video_title(url: str, cookies_file: Optional[Path] = None) -> str:
    """Fetch the real video title from yt-dlp metadata."""
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    cmd = f'yt-dlp --dump-json --no-playlist {cookies_option} "{url}"'
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if stdout.strip():
            info = json.loads(stdout.decode())
            return info.get('title', 'download')
    except Exception as e:
        logger.warning(f"Could not fetch title via dump-json, falling back to --get-title: {e}")

    # Fallback: --get-title is faster but less reliable
    cmd2 = f'yt-dlp --get-title {cookies_option} "{url}"'
    try:
        process2 = await asyncio.create_subprocess_shell(
            cmd2,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout2, _ = await process2.communicate()
        title = stdout2.decode().strip()
        if title:
            return title
    except Exception:
        pass

    return "download"


async def get_video_info_and_url(url: str, format_selector: str, cookies_file: Optional[Path] = None) -> tuple[str, str, str]:
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    cmd = f'yt-dlp --dump-json -f "{format_selector}" {cookies_option} "{url}"'

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if stderr and "ERROR" in stderr.decode():
        logger.error(f"yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail=f"Failed to get video info: {stderr.decode()}")

    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No video information received")

    try:
        info = json.loads(stdout.decode())
        direct_url = info.get('url')
        if not direct_url:
            direct_url = info.get('manifest_url') or info.get('fragment_base_url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid direct URL found")
        title = info.get('title', 'download')
        ext = info.get('ext', 'mp4')
        logger.info(f"Got direct URL: {direct_url[:100]}...")
        return direct_url, title, ext
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse video information")


async def stream_from_url(url: str, headers: dict = None) -> AsyncGenerator[bytes, None]:
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Range': 'bytes=0-'
    }
    if headers:
        default_headers.update(headers)

    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(timeout=timeout, headers=default_headers) as session:
        try:
            async with session.get(url) as response:
                if response.status not in [200, 206]:
                    logger.error(f"HTTP error {response.status} for URL: {url}")
                    raise HTTPException(status_code=500, detail=f"Failed to fetch media: HTTP {response.status}")
                async for chunk in response.content.iter_chunked(8192):
                    yield chunk
        except aiohttp.ClientError as e:
            logger.error(f"Client error streaming from {url}: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")


# ---------------------------------------------------------------------------
# Audio stream endpoint
# ---------------------------------------------------------------------------
# KEY FIX: yt-dlp CANNOT mux two streams (video+audio) when writing to stdout
# (-o -). Only single pre-merged formats work for pipe/streaming.
# For audio we request a single bestaudio stream in priority order.
# For video we use pre-merged mp4 format codes (same strategy as ytdownloader)
# with a fallback chain so the best available quality is always returned.
# ---------------------------------------------------------------------------

AUDIO_FORMAT_CHAINS = {
    # Each quality: list of format selectors tried in order
    '128K': [
        'bestaudio[abr<=128][ext=m4a]',
        'bestaudio[abr<=128]',
        'bestaudio[ext=m4a]',
        'bestaudio',
    ],
    '192K': [
        'bestaudio[abr<=192][ext=m4a]',
        'bestaudio[abr<=192]',
        'bestaudio[ext=m4a]',
        'bestaudio',
    ],
    '320K': [
        'bestaudio[ext=m4a]',
        'bestaudio',
    ],
}

# Pre-merged single-file mp4 format codes, mirroring ytdownloader's approach.
# These are itag codes for formats YouTube already mixes (progressive streams)
# OR the "best" fallback which yt-dlp resolves to a single-file download.
VIDEO_FORMAT_CHAINS = {
    '360p':  ['18', 'best[height<=360][ext=mp4]', 'best[height<=360]', 'best'],
    '480p':  ['135', 'best[height<=480][ext=mp4]', 'best[height<=480]', 'best'],
    '720p':  ['22', 'best[height<=720][ext=mp4]', 'best[height<=720]', 'best'],
    '1080p': ['137', 'best[height<=1080][ext=mp4]', 'best[height<=1080]', 'best'],
    '240p':  ['133', 'best[height<=240][ext=mp4]', 'best[height<=240]', 'best'],
    '144p':  ['160', 'best[height<=144][ext=mp4]', 'best[height<=144]', 'best'],
}


async def resolve_format(url: str, format_chain: list[str], cookies_file: Optional[Path]) -> tuple[str, str]:
    """
    Try each format selector in the chain and return the first one that
    yt-dlp can actually resolve to a direct URL plus the real video title.
    Returns (format_selector_that_worked, video_title).
    """
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    for fmt in format_chain:
        cmd = f'yt-dlp --dump-json --no-playlist -f "{fmt}" {cookies_option} "{url}"'
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0 and stdout.strip():
                info = json.loads(stdout.decode())
                # Make sure we got a real direct URL
                direct_url = info.get('url') or info.get('manifest_url')
                if direct_url and direct_url.startswith('http'):
                    title = info.get('title', 'download')
                    logger.info(f"Format '{fmt}' resolved OK for: {url[:60]}")
                    return fmt, title
        except Exception as e:
            logger.warning(f"Format '{fmt}' failed with exception: {e}")
    raise HTTPException(status_code=500, detail="No compatible format found for this video.")


@router.get("/download/audio")
async def download_youtube_audio(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality (128K, 192K, 320K)")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    valid_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_qualities else '192K'
    cookies_file = get_cookies_file()

    try:
        format_chain = AUDIO_FORMAT_CHAINS[audio_quality]
        fmt, title = await resolve_format(song, format_chain, cookies_file)
        clean_title = sanitize_filename(title)

        direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)

        return StreamingResponse(
            stream_from_url(direct_url),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title} [{audio_quality}].mp3"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
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
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    valid_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_qualities else '720p'
    cookies_file = get_cookies_file()

    try:
        format_chain = VIDEO_FORMAT_CHAINS[video_quality]
        fmt, title = await resolve_format(song, format_chain, cookies_file)
        clean_title = sanitize_filename(title)

        direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)

        return StreamingResponse(
            stream_from_url(direct_url),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title} [{video_quality}].mp4"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
                "X-Content-Type-Options": "nosniff"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.get("/download/audio/redirect")
async def download_youtube_audio_redirect(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    audio_quality = quality if quality in ['128K', '192K', '320K'] else '192K'
    format_chain = AUDIO_FORMAT_CHAINS[audio_quality]

    try:
        fmt, _ = await resolve_format(song, format_chain, cookies_file)
        direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)
        return RedirectResponse(url=direct_url, status_code=302)
    except Exception as e:
        logger.error(f"YouTube audio redirect error: {e}")
        raise HTTPException(status_code=500, detail=f"Redirect failed: {str(e)}")


@router.get("/download/video/redirect")
async def download_youtube_video_redirect(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("720p", description="Video quality")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    video_quality = quality if quality in ['144p', '240p', '360p', '480p', '720p', '1080p'] else '720p'
    format_chain = VIDEO_FORMAT_CHAINS.get(video_quality, VIDEO_FORMAT_CHAINS['720p'])

    try:
        fmt, _ = await resolve_format(song, format_chain, cookies_file)
        direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)
        return RedirectResponse(url=direct_url, status_code=302)
    except Exception as e:
        logger.error(f"YouTube video redirect error: {e}")
        raise HTTPException(status_code=500, detail=f"Redirect failed: {str(e)}")


# ---------------------------------------------------------------------------
# Stream endpoints — pipe yt-dlp stdout directly to the client.
# IMPORTANT: only single-stream (pre-merged) formats work here because
# yt-dlp cannot mux video+audio when writing to stdout (-o -).
# We use resolve_format() to pick the best compatible format first,
# then stream that exact format code.
# ---------------------------------------------------------------------------

@router.get("/download/audio/stream")
async def download_youtube_audio_stream(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    audio_quality = quality if quality in ['128K', '192K', '320K'] else '192K'
    format_chain = AUDIO_FORMAT_CHAINS[audio_quality]

    try:
        # Resolve the best working format and get the real title
        fmt, title = await resolve_format(song, format_chain, cookies_file)
        clean_title = sanitize_filename(title)
        logger.info(f"Streaming audio: '{title}' | format: {fmt} | quality: {audio_quality}")

        async def stream_yt_dlp():
            cmd = ["yt-dlp", "--quiet", "--no-warnings", "-f", fmt, "-o", "-", song]
            if cookies_file:
                cmd.extend(["--cookies", str(cookies_file)])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                while True:
                    chunk = await proc.stdout.read(8388608)
                    if not chunk:
                        break
                    yield chunk
                await proc.wait()
                if proc.returncode != 0:
                    stderr_out = await proc.stderr.read()
                    logger.error(f"yt-dlp streaming error: {stderr_out.decode()}")
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                if proc.returncode is None:
                    proc.terminate()
                    await proc.wait()
                raise

        return StreamingResponse(
            stream_yt_dlp(),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title} [{audio_quality}].mp3"',
                "Cache-Control": "no-cache"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube audio stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")


@router.get("/download/video/stream")
async def download_youtube_video_stream(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("720p", description="Video quality")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    video_quality = quality if quality in ['144p', '240p', '360p', '480p', '720p', '1080p'] else '720p'
    format_chain = VIDEO_FORMAT_CHAINS.get(video_quality, VIDEO_FORMAT_CHAINS['720p'])

    try:
        # Resolve the best working format and get the real title
        fmt, title = await resolve_format(song, format_chain, cookies_file)
        clean_title = sanitize_filename(title)
        logger.info(f"Streaming video: '{title}' | format: {fmt} | quality: {video_quality}")

        async def stream_video():
            cmd = ["yt-dlp", "--quiet", "--no-warnings", "-f", fmt, "-o", "-", song]
            if cookies_file:
                cmd.extend(["--cookies", str(cookies_file)])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                while True:
                    chunk = await proc.stdout.read(8388608)
                    if not chunk:
                        break
                    yield chunk
                await proc.wait()
                if proc.returncode != 0:
                    stderr_out = await proc.stderr.read()
                    logger.error(f"yt-dlp video streaming error: {stderr_out.decode()}")
            except Exception as e:
                logger.error(f"Video stream error: {e}")
                if proc.returncode is None:
                    proc.terminate()
                    await proc.wait()
                raise

        return StreamingResponse(
            stream_video(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title} [{video_quality}].mp4"',
                "Cache-Control": "no-cache"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube video stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Video streaming failed: {str(e)}")
