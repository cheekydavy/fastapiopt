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
        title = info.get('title', 'unknown')
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
        format_selector = f"bestaudio[abr<={audio_quality[:-1]}]/bestaudio/best"
        direct_url, title, ext = await get_video_info_and_url(song, format_selector, cookies_file)
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)

        return StreamingResponse(
            stream_from_url(direct_url),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}_{audio_quality}.mp3"',
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
        quality_formats = {
            '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
            '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
            '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        }
        format_selector = quality_formats.get(video_quality, 'bestvideo[height<=720]+bestaudio/best')
        direct_url, title, ext = await get_video_info_and_url(song, format_selector, cookies_file)
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)

        return StreamingResponse(
            stream_from_url(direct_url),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}_{video_quality}.mp4"',
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
    format_selector = f"bestaudio[abr<={audio_quality[:-1]}]/bestaudio/best"

    try:
        direct_url, title, ext = await get_video_info_and_url(song, format_selector, cookies_file)
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

    quality_formats = {
        '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
        '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
        '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
        '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
        '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    }
    format_selector = quality_formats.get(video_quality, 'bestvideo[height<=720]+bestaudio/best')

    try:
        direct_url, title, ext = await get_video_info_and_url(song, format_selector, cookies_file)
        return RedirectResponse(url=direct_url, status_code=302)
    except Exception as e:
        logger.error(f"YouTube video redirect error: {e}")
        raise HTTPException(status_code=500, detail=f"Redirect failed: {str(e)}")


@router.get("/download/audio/stream")
async def download_youtube_audio_stream(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    audio_quality = quality if quality in ['128K', '192K', '320K'] else '192K'

    try:
        title_cmd = f'yt-dlp --get-title {cookies_option} "{song}"'
        process = await asyncio.create_subprocess_shell(
            title_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        title = stdout.decode().strip() if stdout else "audio"
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)

        async def stream_yt_dlp():
            cmd = [
                "yt-dlp",
                "--quiet",
                "--no-warnings",
                "-f", f"bestaudio[abr<={audio_quality[:-1]}]/bestaudio/best",
                "-o", "-",
                song
            ]
            if cookies_file:
                cmd.extend(["--cookies", str(cookies_file)])

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                while True:
                    chunk = await process.stdout.read(8388608)
                    if not chunk:
                        break
                    yield chunk
                await process.wait()
                if process.returncode != 0:
                    stderr_output = await process.stderr.read()
                    logger.error(f"yt-dlp streaming error: {stderr_output.decode()}")
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
                raise

        return StreamingResponse(
            stream_yt_dlp(),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}_{audio_quality}.mp3"',
                "Cache-Control": "no-cache"
            }
        )
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
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    video_quality = quality if quality in ['144p', '240p', '360p', '480p', '720p', '1080p'] else '720p'

    quality_formats = {
        '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
        '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
        '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
        '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
        '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    }

    try:
        title_cmd = f'yt-dlp --get-title {cookies_option} "{song}"'
        process = await asyncio.create_subprocess_shell(
            title_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        title = stdout.decode().strip() if stdout else "video"
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
        format_selector = quality_formats.get(video_quality, 'bestvideo[height<=720]+bestaudio/best')

        async def stream_video():
            cmd = [
                "yt-dlp",
                "--quiet",
                "--no-warnings",
                "-f", format_selector,
                "-o", "-",
                song
            ]
            if cookies_file:
                cmd.extend(["--cookies", str(cookies_file)])

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                while True:
                    chunk = await process.stdout.read(8388608)
                    if not chunk:
                        break
                    yield chunk
                await process.wait()
                if process.returncode != 0:
                    stderr_output = await process.stderr.read()
                    logger.error(f"yt-dlp video streaming error: {stderr_output.decode()}")
            except Exception as e:
                logger.error(f"Video stream error: {e}")
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
                raise

        return StreamingResponse(
            stream_video(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}_{video_quality}.mp4"',
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        logger.error(f"YouTube video stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Video streaming failed: {str(e)}")
