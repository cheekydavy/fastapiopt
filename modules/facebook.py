from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
import asyncio
import yt_dlp
import uuid
import logging
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

@router.get("/api/fburl")
async def download_facebook_video(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Facebook URL")
):
    """Download Facebook video"""
    if not ("facebook.com" in url or "fb.watch" in url):
        raise HTTPException(status_code=400, detail="Invalid Facebook URL")
    
    try:
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
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
        
        title = info.get('title', 'facebook_video')
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}.mp4",
            media_type="video/mp4"
        )
        
    except Exception as e:
        logger.error(f"Facebook download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
