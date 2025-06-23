from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
import asyncio
import os
import uuid
import urllib.parse
import logging
import yt_dlp
import re
from pathlib import Path

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

def sanitize_filename(value: str) -> str:
    """Sanitize filename to remove invalid characters"""
    if not value:
        return "Unknown_Title"
    sanitized = re.sub(r'[^\w\s-]', '', value)
    sanitized = re.sub(r'\s+', '_', sanitized).strip()
    return sanitized or "Unknown_Title"

async def extract_tiktok_info(url: str) -> tuple[str, str]:
    """Extract video info using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
    }
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            thumbnail = info.get('thumbnail', '')
            title = sanitize_filename(info.get('title', 'Unknown Title'))
            return thumbnail, title
    except Exception as e:
        logger.error(f"Failed to extract TikTok info: {e}")
        return '', 'Unknown_Title'

async def run_command(command: list) -> tuple[int, str]:
    """Run command asynchronously"""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stderr.decode()

@router.get("/api/tiktokurl")
async def download_tiktok_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="TikTok URL")
):
    """Download TikTok video"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok video URL: {decoded_url}")
        
        # Extract video info
        thumbnail, title = await extract_tiktok_info(decoded_url)
        
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.mp4"
        output_path = temp_dir / filename
        
        # Download video
        cmd = [
            "yt-dlp",
            "--retries", "3",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", str(output_path),
            decoded_url
        ]
        
        returncode, stderr = await run_command(cmd)
        
        if returncode != 0 or not output_path.exists():
            logger.error(f"TikTok download failed: {stderr}")
            raise HTTPException(status_code=500, detail="Download failed")
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp4",
            media_type="video/mp4",
            headers={
                "x-tiktok-thumbnail": thumbnail or "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok video download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("/api/tiktoaudio")
async def download_tiktok_audio(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="TikTok URL")
):
    """Download TikTok audio"""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        if not (decoded_url.startswith("https://www.tiktok.com/") or 
                decoded_url.startswith("https://vm.tiktok.com/") or
                decoded_url.startswith("https://vt.tiktok.com/")):
            raise HTTPException(status_code=400, detail="Invalid TikTok URL")
        
        logger.info(f"Processing TikTok audio URL: {decoded_url}")
        
        # Extract video info
        thumbnail, title = await extract_tiktok_info(decoded_url)
        
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.mp3"
        output_path = temp_dir / filename
        
        # Download audio
        cmd = [
            "yt-dlp",
            "--retries", "3",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "-o", str(output_path),
            decoded_url
        ]
        
        returncode, stderr = await run_command(cmd)
        
        if returncode != 0 or not output_path.exists():
            logger.error(f"TikTok audio download failed: {stderr}")
            raise HTTPException(status_code=500, detail="Download failed")
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp3",
            media_type="audio/mpeg",
            headers={
                "x-tiktok-thumbnail": thumbnail or "https://i.ibb.co/rRS0Y9rP/d0fa360c97e1c383.jpg",
                "x-tiktok-title": title
            }
        )
        
    except Exception as e:
        logger.error(f"TikTok audio download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
