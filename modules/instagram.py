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

@router.get("/download/iglink")
async def download_instagram_media(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Instagram URL")
):
    """Download Instagram media (video/image)"""
    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        raise HTTPException(status_code=400, detail="Invalid Instagram URL")
    
    try:
        # Create temp directory
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}.%(ext)s"
        output_template = str(temp_dir / filename)
        
        ydl_opts = {
            'outtmpl': output_template,
            'format': 'best',
            'merge_output_format': 'mp4',
            'no_cache_dir': True,
            'quiet': True,
        }
        
        loop = asyncio.get_event_loop()
        
        def download_media():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                actual_filename = ydl.prepare_filename(info)
                return actual_filename, info
        
        actual_filename, info = await loop.run_in_executor(None, download_media)
        output_path = Path(actual_filename)
        
        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Download failed - file not found")
        
        # Determine media type and filename
        title = info.get('title', 'instagram_media')
        ext = output_path.suffix or '.mp4'
        media_type = 'video/mp4' if ext in ['.mp4', '.mov'] else 'image/jpeg'
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}{ext}",
            media_type=media_type
        )
        
    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
