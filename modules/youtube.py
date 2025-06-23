from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import subprocess
import os
import re
import json
import logging
from pathlib import Path
import time
import tempfile
from typing import Optional, AsyncGenerator
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

def get_cookies_file() -> Path:
    """Find cookies file in various possible locations"""
    possible_paths = [
        Path('cookies.txt'),  # Root directory
        Path('/app/cookies.txt'),  # Docker container root
        Path('modules/cookies.txt'),  # Modules directory
        Path('/app/modules/cookies.txt'),  # Docker modules directory
        Path(os.getcwd()) / 'cookies.txt',  # Current working directory
    ]
    
    for path in possible_paths:
        if path.exists():
            logger.info(f"Found cookies file at: {path}")
            return path
    
    logger.warning("No cookies file found in any of the expected locations")
    logger.info(f"Searched in: {[str(p) for p in possible_paths]}")
    return None

def is_valid_youtube_url(url: str) -> bool:
    """Validate YouTube URL"""
    pattern = r'^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/(watch\?v=|shorts\/|embed\/)?[A-Za-z0-9_-]{11}(\?.*)?$'
    return bool(re.match(pattern, url))

async def run_command(command: str) -> tuple[str, str]:
    """Run shell command asynchronously"""
    logger.info(f"Running command: {command}")
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return stdout.decode(), stderr.decode()

async def get_video_info_and_url(url: str, format_selector: str, cookies_file: Optional[Path] = None) -> tuple[str, str, str]:
    """Get video info and direct URL using yt-dlp JSON output"""
    cookies_option = f'--cookies "{cookies_file}"' if cookies_file else ""
    
    # Use JSON output to get both metadata and URL
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
        # Handle multiple JSON objects (for video+audio format)
        json_lines = [line.strip() for line in stdout.decode().strip().split('\n') if line.strip()]
        
        # Try to find the best format
        direct_url = None
        title = 'unknown'
        ext = 'mp4'
        
        for json_line in json_lines:
            try:
                info = json.loads(json_line)
                
                # Get the direct URL
                url_candidate = info.get('url')
                if url_candidate and url_candidate.startswith('http'):
                    direct_url = url_candidate
                    title = info.get('title', title)
                    ext = info.get('ext', ext)
                    break
                    
            except json.JSONDecodeError:
                continue
        
        # If no direct URL found, try alternative approach
        if not direct_url:
            # Try with simpler format selector
            simple_cmd = f'yt-dlp --dump-json -f "best" {cookies_option} "{url}"'
            process = await asyncio.create_subprocess_shell(
                simple_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if stdout.strip():
                info = json.loads(stdout.decode())
                direct_url = info.get('url')
                title = info.get('title', 'unknown')
                ext = info.get('ext', 'mp4')
        
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid direct URL found")
        
        logger.info(f"Got direct URL: {direct_url[:100]}...")
        
        return direct_url, title, ext
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse video information")

async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with 2MB chunks"""
    # Add user agent and other headers to avoid blocking
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Range': 'bytes=0-'
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url) as response:
                if response.status not in [200, 206]:
                    logger.error(f"HTTP error {response.status} for URL: {url}")
                    raise HTTPException(status_code=500, detail=f"Failed to fetch media: HTTP {response.status}")
                
                # Stream the content in larger chunks (2MB)
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
                    
        except aiohttp.ClientError as e:
            logger.error(f"Client error streaming from {url}: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")

# ORIGINAL ENDPOINTS (KEEP AS-IS)
@router.get("/download/audio")
async def download_youtube_audio(
    background_tasks: BackgroundTasks,
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality (128K, 192K, 320K)")
):
    """Download YouTube audio (Original endpoint - file-based)"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_qualities else '192K'
    
    cookies_file = get_cookies_file()
    if not cookies_file:
        logger.warning("No cookies file found - attempting download without cookies")
        # Don't raise an exception, try without cookies
        cookies_option = ""
    else:
        cookies_option = f'--cookies "{cookies_file}"'
    
    try:
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Get video info
        metadata_cmd = f'yt-dlp --dump-json {cookies_option} "{song}"'
        stdout, stderr = await run_command(metadata_cmd)
        
        if stderr and "ERROR" in stderr:
            logger.error(f"Metadata error: {stderr}")
            raise HTTPException(status_code=500, detail=f"Failed to get video info: {stderr}")
        
        if not stdout.strip():
            raise HTTPException(status_code=500, detail="No video information received")
        
        try:
            video_info = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}, stdout: {stdout[:500]}")
            raise HTTPException(status_code=500, detail="Failed to parse video information")
        
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info.get('title', 'unknown'))
        
        # Generate unique filename
        cache_buster = str(int(time.time()))
        output_file = temp_dir / f"{video_title}_{audio_quality}_{cache_buster}.%(ext)s"
        
        # Download audio
        download_cmd = f'yt-dlp -x --audio-format mp3 --audio-quality {audio_quality} {cookies_option} -o "{output_file}" "{song}"'
        stdout, stderr = await run_command(download_cmd)
        
        # Find the actual downloaded file
        downloaded_files = list(temp_dir.glob(f"{video_title}_{audio_quality}_{cache_buster}.*"))
        if not downloaded_files:
            logger.error(f"Download stderr: {stderr}")
            logger.error(f"Download stdout: {stdout}")
            raise HTTPException(status_code=500, detail="Failed to download audio - file not found")
        
        actual_file = downloaded_files[0]
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, actual_file)
        
        return FileResponse(
            path=str(actual_file),
            filename=f"{video_title}_{audio_quality}.mp3",
            media_type="audio/mpeg"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("/download/video")
async def download_youtube_video(
    background_tasks: BackgroundTasks,
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("720p", description="Video quality (144p, 240p, 360p, 480p, 720p, 1080p)")
):
    """Download YouTube video (Original endpoint - file-based)"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_qualities else '720p'
    
    cookies_file = get_cookies_file()
    if not cookies_file:
        logger.warning("No cookies file found - attempting download without cookies")
        cookies_option = ""
    else:
        cookies_option = f'--cookies "{cookies_file}"'
    
    try:
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Get video info
        metadata_cmd = f'yt-dlp --dump-json {cookies_option} "{song}"'
        stdout, stderr = await run_command(metadata_cmd)
        
        if stderr and "ERROR" in stderr:
            logger.error(f"Metadata error: {stderr}")
            raise HTTPException(status_code=500, detail=f"Failed to get video info: {stderr}")
        
        if not stdout.strip():
            raise HTTPException(status_code=500, detail="No video information received")
        
        try:
            video_info = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}, stdout: {stdout[:500]}")
            raise HTTPException(status_code=500, detail="Failed to parse video information")
        
        video_title = re.sub(r'[^a-zA-Z0-9]', '_', video_info.get('title', 'unknown'))
        
        # Generate unique filename
        cache_buster = str(int(time.time()))
        output_file = temp_dir / f"{video_title}_{video_quality}_{cache_buster}.%(ext)s"
        
        # Quality format mapping
        quality_formats = {
            '144p': 'bestvideo[height<=144]+bestaudio/best[height<=144]',
            '240p': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
            '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        }
        
        format_selector = quality_formats.get(video_quality, 'bestvideo[height<=720]+bestaudio/best')
        
        # Download video
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        download_cmd = f'yt-dlp --user-agent "{user_agent}" -f "{format_selector}" --merge-output-format mp4 {cookies_option} -o "{output_file}" "{song}"'
        stdout, stderr = await run_command(download_cmd)
        
        # Find the actual downloaded file
        downloaded_files = list(temp_dir.glob(f"{video_title}_{video_quality}_{cache_buster}.*"))
        if not downloaded_files:
            logger.error(f"Download stderr: {stderr}")
            logger.error(f"Download stdout: {stdout}")
            raise HTTPException(status_code=500, detail="Failed to download video - file not found")
        
        actual_file = downloaded_files[0]
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, actual_file)
        
        return FileResponse(
            path=str(actual_file),
            filename=f"{video_title}_{video_quality}.mp4",
            media_type="video/mp4"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# NEW STREAMING ENDPOINTS (FOR WEBSITE)
@router.get("/stream/audio")
async def stream_youtube_audio(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality (128K, 192K, 320K)")
):
    """Stream YouTube audio - shows browser download progress"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['128K', '192K', '320K']
    audio_quality = quality if quality in valid_qualities else '192K'
    
    cookies_file = get_cookies_file()
    
    try:
        # Format selector for audio
        format_selector = f"bestaudio[abr<={audio_quality[:-1]}]/bestaudio/best"
        
        # Get video info and direct URL
        direct_url, title, ext = await get_video_info_and_url(song, format_selector, cookies_file)
        
        # Clean filename
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
        
        # Stream directly from the URL with 2MB chunks
        return StreamingResponse(
            stream_from_url(direct_url, chunk_size=2097152),  # 2MB chunks
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
        logger.error(f"YouTube audio stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")

@router.get("/stream/video")
async def stream_youtube_video(
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("720p", description="Video quality (144p, 240p, 360p, 480p, 720p, 1080p)")
):
    """Stream YouTube video - shows browser download progress"""
    if not song or not is_valid_youtube_url(song):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    valid_qualities = ['144p', '240p', '360p', '480p', '720p', '1080p']
    video_quality = quality if quality in valid_qualities else '720p'
    
    cookies_file = get_cookies_file()
    
    try:
        # Simplified quality format mapping for better compatibility
        quality_formats = {
            '144p': 'worst[height<=144]/worst',
            '240p': 'worst[height<=240]/worst',
            '360p': 'best[height<=360]/best[height<=480]/best',
            '480p': 'best[height<=480]/best[height<=720]/best',
            '720p': 'best[height<=720]/best',
            '1080p': 'best[height<=1080]/best'
        }
        
        format_selector = quality_formats.get(video_quality, 'best')
        
        # Get video info and direct URL
        direct_url, title, ext = await get_video_info_and_url(song, format_selector, cookies_file)
        
        # Clean filename
        clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
        
        # Stream directly from the URL with 2MB chunks
        return StreamingResponse(
            stream_from_url(direct_url, chunk_size=2097152),  # 2MB chunks
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
        logger.error(f"YouTube video stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")
