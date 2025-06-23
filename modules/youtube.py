from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
import asyncio
import subprocess
import os
import re
import json
import logging
from pathlib import Path
import time
import tempfile
from typing import Optional

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

@router.get("/download/audio")
async def download_youtube_audio(
    background_tasks: BackgroundTasks,
    song: str = Query(..., description="YouTube URL"),
    quality: Optional[str] = Query("192K", description="Audio quality (128K, 192K, 320K)")
):
    """Download YouTube audio"""
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
    """Download YouTube video"""
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
