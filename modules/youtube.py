from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, RedirectResponse, FileResponse
import asyncio
import os
import re
import json
import logging
import uuid
from pathlib import Path
import time
from typing import Optional, AsyncGenerator
import aiohttp

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

# JS runtime flags required for YouTube n-challenge & signature solving.
# Without these, yt-dlp cannot decrypt formats and falls back to images only.
# Mirrors ytdownloader: --js-runtimes node --remote-components ejs:github
JS_ARGS = ["--js-runtimes", "node", "--remote-components", "ejs:github"]
JS_OPTS = ' '.join(JS_ARGS)  # shell-string version for create_subprocess_shell calls


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
    """Preserve real title, strip only filesystem-unsafe characters."""
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name).strip()
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned or "download"


async def get_video_title(url: str, cookies_file: Optional[Path] = None) -> str:
    """Fetch the real video title via --dump-json."""
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    cmd = f'yt-dlp --dump-json --no-playlist {JS_OPTS} {cookies_option} "{url}"'
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        if stdout.strip():
            info = json.loads(stdout.decode())
            return info.get('title', 'download')
    except Exception as e:
        logger.warning(f"dump-json title fetch failed: {e}")

    # Fallback: --get-title
    cmd2 = f'yt-dlp --get-title {JS_OPTS} {cookies_option} "{url}"'
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
    cmd = f'yt-dlp --dump-json --no-playlist -f "{format_selector}" {JS_OPTS} {cookies_option} "{url}"'

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if stderr and "ERROR" in stderr.decode():
        raise HTTPException(status_code=500, detail=f"Failed to get video info: {stderr.decode()}")

    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No video information received")

    try:
        info = json.loads(stdout.decode())
        direct_url = info.get('url') or info.get('manifest_url') or info.get('fragment_base_url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid direct URL found")
        title = info.get('title', 'download')
        ext = info.get('ext', 'mp4')
        return direct_url, title, ext
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="Failed to parse video information")


async def stream_from_url(url: str, headers: dict = None) -> AsyncGenerator[bytes, None]:
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Range': 'bytes=0-'
    }
    if headers:
        default_headers.update(headers)

    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(timeout=timeout, headers=default_headers) as session:
        async with session.get(url) as response:
            if response.status not in [200, 206]:
                raise HTTPException(status_code=500, detail=f"Failed to fetch media: HTTP {response.status}")
            async for chunk in response.content.iter_chunked(8192):
                yield chunk


# ---------------------------------------------------------------------------
# Format chains
#
# KEY INSIGHT from ytdownloader: yt-dlp CANNOT mux video+audio to stdout.
# For stream endpoints we must download to a temp file (using --merge-output-format
# so ffmpeg can combine the streams), then serve from disk — exactly how
# ytdownloader works. We use the same fallback format-code strategy.
#
# For /download/audio and /download/video (non-stream), we use pre-merged
# single-stream direct URLs via aiohttp proxy.
# ---------------------------------------------------------------------------

# Audio: single stream formats (no muxing needed)
AUDIO_FORMAT_CHAINS = {
    '128K': ['bestaudio[abr<=128][ext=m4a]', 'bestaudio[abr<=128]', 'bestaudio[ext=m4a]', 'bestaudio'],
    '192K': ['bestaudio[abr<=192][ext=m4a]', 'bestaudio[abr<=192]', 'bestaudio[ext=m4a]', 'bestaudio'],
    '320K': ['bestaudio[ext=m4a]', 'bestaudio'],
}

# Video format chains — mirrors ytdownloader quality_format_map with fallbacks.
# Format codes are itag numbers for progressive (pre-merged) mp4 streams,
# which work for both direct-url streaming AND file download.
# The height-based fallbacks cover videos that don't have those specific itags.
VIDEO_FORMAT_CHAINS = {
    '144p': ['160+140', '160+251', 'best[height<=144][ext=mp4]', 'best[height<=144]', 'best'],
    '240p': ['133+140', '133+251', 'best[height<=240][ext=mp4]', 'best[height<=240]', 'best'],
    '360p': ['18', '134+140', '134+251', 'best[height<=360][ext=mp4]', 'best[height<=360]', 'best'],
    '480p': ['135+140', '135+251', 'best[height<=480][ext=mp4]', 'best[height<=480]', 'best'],
    '720p': ['22', '136+140', '136+251', 'best[height<=720][ext=mp4]', 'best[height<=720]', 'best'],
    '1080p': ['137+140', '137+251', 'best[height<=1080][ext=mp4]', 'best[height<=1080]', 'best'],
}


async def download_to_temp(url: str, format_selector: str, output_path: Path,
                           cookies_file: Optional[Path], extra_args: list = None) -> tuple[bool, str]:
    """
    Download using yt-dlp to a temp file.
    Returns (success, stderr_output).
    Mirrors ytdownloader's subprocess.run approach but async.
    """
    cmd = [
        "yt-dlp",
        "-f", format_selector,
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-playlist",
    ] + JS_ARGS
    if cookies_file:
        cmd.extend(["--cookies", str(cookies_file)])
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(url)

    logger.info(f"[yt-dlp] Running: {' '.join(cmd)}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    stderr_str = stderr.decode()

    if process.returncode != 0:
        logger.error(f"[yt-dlp] Failed (code {process.returncode}): {stderr_str}")
        return False, stderr_str

    # yt-dlp may produce .mp4, .mkv etc — find whatever it created
    return True, stderr_str


async def download_to_temp_audio(url: str, format_selector: str, output_path: Path,
                                 audio_quality: str, cookies_file: Optional[Path]) -> bool:
    """Download and convert audio to mp3 via yt-dlp -x."""
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", audio_quality,
        "-o", str(output_path),
        "--no-playlist",
    ] + JS_ARGS
    if cookies_file:
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(url)

    logger.info(f"[yt-dlp audio] Running: {' '.join(cmd)}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error(f"[yt-dlp audio] Failed: {stderr.decode()}")
        return False
    return True


async def find_output_file(base_path: Path) -> Optional[Path]:
    """
    yt-dlp may append an extension or change it (e.g. .mp4, .mkv, .webm).
    Find the actual output file by stem.
    """
    parent = base_path.parent
    stem = base_path.stem
    for f in parent.iterdir():
        if f.stem == stem and f.is_file():
            return f
    return None


async def stream_file_response(file_path: Path, media_type: str,
                               download_name: str) -> StreamingResponse:
    """Stream a file from disk, deleting it after."""
    file_size = file_path.stat().st_size

    async def file_streamer():
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(1024 * 1024):  # 1MB chunks
                    yield chunk
        finally:
            try:
                file_path.unlink()
                logger.info(f"Cleaned up temp file: {file_path}")
            except Exception:
                pass

    return StreamingResponse(
        file_streamer(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Content-Length": str(file_size),
            "Cache-Control": "no-cache",
        }
    )


# ---------------------------------------------------------------------------
# /download/audio and /download/video — proxy via direct URL (no muxing)
# ---------------------------------------------------------------------------

@router.get("/download/audio")
async def download_youtube_audio(
    song: str = Query(...),
    quality: Optional[str] = Query("192K")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    valid_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_qualities else '192K'
    cookies_file = get_cookies_file()
    format_chain = AUDIO_FORMAT_CHAINS[audio_quality]

    title = await get_video_title(song, cookies_file)
    clean_title = sanitize_filename(title)

    for fmt in format_chain:
        try:
            direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)
            return StreamingResponse(
                stream_from_url(direct_url),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": f'attachment; filename="{clean_title} [{audio_quality}].mp3"',
                    "Cache-Control": "no-cache",
                }
            )
        except Exception as e:
            logger.warning(f"Audio format '{fmt}' failed: {e}")
            continue

    raise HTTPException(status_code=500, detail="No compatible audio format found.")


@router.get("/download/video")
async def download_youtube_video(
    song: str = Query(...),
    quality: Optional[str] = Query("720p")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    valid_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_qualities else '720p'
    cookies_file = get_cookies_file()
    format_chain = VIDEO_FORMAT_CHAINS[video_quality]

    title = await get_video_title(song, cookies_file)
    clean_title = sanitize_filename(title)

    for fmt in format_chain:
        try:
            direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)
            return StreamingResponse(
                stream_from_url(direct_url),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="{clean_title} [{video_quality}].mp4"',
                    "Cache-Control": "no-cache",
                }
            )
        except Exception as e:
            logger.warning(f"Video format '{fmt}' failed: {e}")
            continue

    raise HTTPException(status_code=500, detail="No compatible video format found.")


# ---------------------------------------------------------------------------
# /download/audio/stream and /download/video/stream
#
# These use yt-dlp to download to a TEMP FILE (with ffmpeg merge), then
# serve the file — same approach as ytdownloader. This is the only reliable
# way to get merged 1080p/720p video+audio without a separate ffmpeg step.
# ---------------------------------------------------------------------------

@router.get("/download/audio/stream")
async def download_youtube_audio_stream(
    song: str = Query(...),
    quality: Optional[str] = Query("192K")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    audio_quality = quality if quality in ['128K', '192K', '320K'] else '192K'

    # Get real title first
    title = await get_video_title(song, cookies_file)
    clean_title = sanitize_filename(title)
    logger.info(f"Audio stream: '{title}' | quality: {audio_quality}")

    # Temp file path (without extension — yt-dlp adds it)
    temp_id = str(uuid.uuid4())
    temp_base = TEMP_DIR / temp_id
    temp_mp3 = TEMP_DIR / f"{temp_id}.mp3"

    success = await download_to_temp_audio(song, "bestaudio/best", temp_base, audio_quality, cookies_file)

    # Find actual output (yt-dlp writes to temp_id.mp3 after -x --audio-format mp3)
    output_file = temp_mp3 if temp_mp3.exists() else await find_output_file(temp_base)

    if not success or not output_file or not output_file.exists():
        logger.error("Audio download to temp failed")
        raise HTTPException(status_code=500, detail="Audio download failed. Try again.")

    if output_file.stat().st_size == 0:
        output_file.unlink()
        raise HTTPException(status_code=500, detail="Downloaded audio file is empty.")

    logger.info(f"Audio ready: {output_file} ({output_file.stat().st_size} bytes)")
    return await stream_file_response(output_file, "audio/mpeg", f"{clean_title} [{audio_quality}].mp3")


@router.get("/download/video/stream")
async def download_youtube_video_stream(
    song: str = Query(...),
    quality: Optional[str] = Query("720p")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    video_quality = quality if quality in ['144p', '240p', '360p', '480p', '720p', '1080p'] else '720p'
    format_chain = VIDEO_FORMAT_CHAINS[video_quality]

    # Get real title first
    title = await get_video_title(song, cookies_file)
    clean_title = sanitize_filename(title)
    logger.info(f"Video stream: '{title}' | quality: {video_quality}")

    # Try each format in the chain — mirrors ytdownloader's fallback loop
    temp_id = str(uuid.uuid4())
    temp_base = TEMP_DIR / f"{temp_id}.mp4"
    output_file = None

    for fmt in format_chain:
        success, stderr = await download_to_temp(song, fmt, temp_base, cookies_file)
        # Find actual file (may have different extension after merge)
        candidate = await find_output_file(TEMP_DIR / temp_id)
        if not candidate:
            candidate = temp_base if temp_base.exists() else None

        if success and candidate and candidate.exists() and candidate.stat().st_size > 0:
            output_file = candidate
            logger.info(f"Format '{fmt}' succeeded → {output_file}")
            break
        else:
            logger.warning(f"Format '{fmt}' failed or produced empty file, trying next...")
            # Clean up any partial file
            for f in TEMP_DIR.glob(f"{temp_id}*"):
                try:
                    f.unlink()
                except Exception:
                    pass

    if not output_file or not output_file.exists():
        raise HTTPException(status_code=500, detail="Video download failed with all formats. Try a lower quality.")

    logger.info(f"Video ready: {output_file} ({output_file.stat().st_size} bytes)")
    return await stream_file_response(output_file, "video/mp4", f"{clean_title} [{video_quality}].mp4")


# ---------------------------------------------------------------------------
# Redirect endpoints (unchanged logic, updated to use format chains)
# ---------------------------------------------------------------------------

@router.get("/download/audio/redirect")
async def download_youtube_audio_redirect(
    song: str = Query(...),
    quality: Optional[str] = Query("192K")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    audio_quality = quality if quality in ['128K', '192K', '320K'] else '192K'

    for fmt in AUDIO_FORMAT_CHAINS[audio_quality]:
        try:
            direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)
            return RedirectResponse(url=direct_url, status_code=302)
        except Exception:
            continue

    raise HTTPException(status_code=500, detail="Redirect failed: no format available.")


@router.get("/download/video/redirect")
async def download_youtube_video_redirect(
    song: str = Query(...),
    quality: Optional[str] = Query("720p")
):
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    cookies_file = get_cookies_file()
    video_quality = quality if quality in ['144p', '240p', '360p', '480p', '720p', '1080p'] else '720p'

    for fmt in VIDEO_FORMAT_CHAINS.get(video_quality, VIDEO_FORMAT_CHAINS['720p']):
        try:
            direct_url, _, _ = await get_video_info_and_url(song, fmt, cookies_file)
            return RedirectResponse(url=direct_url, status_code=302)
        except Exception:
            continue

    raise HTTPException(status_code=500, detail="Redirect failed: no format available.")
