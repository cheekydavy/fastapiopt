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
import os
from apify_client import ApifyClient

router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Apify client with your API token (set via environment variable for security)
APIFY_API_TOKEN = os.environ.get('APIFY_API_TOKEN', '<YOUR_API_TOKEN>')
client = ApifyClient(APIFY_API_TOKEN)

def cleanup_file(file_path: Path):
    """Background task to cleanup temporary files"""
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup {file_path}: {e}")

async def run_apify_instagram_scraper(url: str) -> dict:
    """Run Apify Instagram Scraper and get media info using apify_client"""
    if not APIFY_API_TOKEN:
        raise ValueError("APIFY_API_TOKEN environment variable not set")
    
    try:
        run_input = {
            "directUrls": [url],
            "resultsType": "posts",
            "resultsLimit": 1,
            "searchType": "hashtag",
            "searchLimit": 1,
            "addParentData": False,
        }
        
        # Run the Actor and wait for it to finish (sync, wrapped in executor for async)
        loop = asyncio.get_event_loop()
        run = await loop.run_in_executor(
            None,
            lambda: client.actor("shu8hvrXbJbY3Eb9W").call(run_input=run_input)
        )
        dataset_id = run["defaultDatasetId"]
        
        # Fetch results from the run's dataset (sync, wrapped)
        items = await loop.run_in_executor(
            None,
            lambda: list(client.dataset(dataset_id).iterate_items())
        )
        
        if not items:
            raise ValueError("No data from Apify scraper")
        
        first_item = items[0]
        logger.info(f"Apify scraped: {first_item.get('displayUrl', 'No URL')[:100]}...")
        return first_item
    except Exception as e:
        logger.error(f"Apify failed: {str(e)}")
        raise

async def get_instagram_info_and_url(url: str) -> tuple[str, str, str]:
    """Get Instagram info and direct URL using JSON output"""
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
        logger.error(f"Instagram yt-dlp error: {stderr.decode()}")
        raise HTTPException(status_code=500, detail="Failed to get Instagram info")
    
    if not stdout.strip():
        raise HTTPException(status_code=500, detail="No Instagram info received")
    
    try:
        info = json.loads(stdout.decode())
        
        direct_url = info.get('url')
        if not direct_url or not direct_url.startswith('http'):
            raise HTTPException(status_code=500, detail="No valid Instagram URL found")
        
        title = info.get('title', 'instagram_media')
        ext = info.get('ext', 'mp4')
        
        logger.info(f"Got Instagram direct URL: {direct_url[:100]}...")
        
        return direct_url, title, ext
        
    except json.JSONDecodeError as e:
        logger.error(f"Instagram JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse Instagram info")

async def stream_from_url(url: str, chunk_size: int = 2097152) -> AsyncGenerator[bytes, None]:
    """Stream content directly from URL with 2MB chunks and Instagram-specific headers"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Referer': 'https://www.instagram.com/',
        'Origin': 'https://www.instagram.com',
        'Sec-Fetch-Dest': 'video',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site'
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status not in [200, 206]:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch Instagram media: HTTP {response.status}")
                
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
                    
        except aiohttp.ClientError as e:
            logger.error(f"Instagram streaming error: {e}")
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")

# ORIGINAL ENDPOINT (MODIFIED WITH APIFY PRIMARY)
@router.get("/download/iglink")
async def download_instagram_media(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Instagram URL")
):
    """Download Instagram media (video/image) - Apify primary, yt-dlp fallback"""
    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        raise HTTPException(status_code=400, detail="Invalid Instagram URL")
    
    try:
        # Primary: Try Apify
        try:
            apify_data = await run_apify_instagram_scraper(url)
            # Download from Apify-provided URL to temp
            direct_url = apify_data.get('videoUrl') or apify_data.get('imageUrl') or apify_data.get('displayUrl')
            if not direct_url:
                raise ValueError("No media URL in Apify data")
            
            title = apify_data.get('title', 'instagram_media')
            ext = 'mp4' if 'videoUrl' in apify_data else 'jpg'
            
            # Create temp directory and file
            temp_dir = Path('temp')
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / f"{uuid.uuid4()}.{ext}"
            
            # Download the file
            async with aiohttp.ClientSession() as session:
                async with session.get(direct_url) as resp:
                    if resp.status != 200:
                        raise HTTPException(status_code=500, detail=f"Apify media download failed: HTTP {resp.status}")
                    content = await resp.read()
                    with open(temp_file, 'wb') as f:
                        f.write(content)
            
            if not temp_file.exists():
                raise HTTPException(status_code=500, detail="Apify download failed - file not found")
            
            media_type = 'video/mp4' if ext == 'mp4' else 'image/jpeg'
            
            # Schedule cleanup
            background_tasks.add_task(cleanup_file, temp_file)
            
            return FileResponse(
                path=str(temp_file),
                filename=f"{title}.{ext}",
                media_type=media_type
            )
        except Exception as apify_err:
            logger.warning(f"Apify failed: {apify_err}. Falling back to yt-dlp.")
        
        # Fallback: Original yt-dlp logic
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)
        
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
        
        title = info.get('title', 'instagram_media')
        ext = output_path.suffix or '.mp4'
        media_type = 'video/mp4' if ext in ['.mp4', '.mov'] else 'image/jpeg'
        
        background_tasks.add_task(cleanup_file, output_path)
        
        return FileResponse(
            path=str(output_path),
            filename=f"{title}{ext}",
            media_type=media_type
        )
        
    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# NEW STREAMING ENDPOINT (MODIFIED WITH APIFY PRIMARY)
@router.get("/stream/iglink")
async def stream_instagram_media(
    url: str = Query(..., description="Instagram URL")
):
    """Stream Instagram media with browser progress - Apify primary, yt-dlp fallback"""
    if not (url.startswith('https://www.instagram.com/') or url.startswith('https://instagr.am/')):
        raise HTTPException(status_code=400, detail="Invalid Instagram URL")
    
    try:
        # Primary: Try Apify
        try:
            apify_data = await run_apify_instagram_scraper(url)
            direct_url = apify_data.get('videoUrl') or apify_data.get('imageUrl') or apify_data.get('displayUrl')
            if not direct_url:
                raise ValueError("No media URL in Apify data")
            
            title = apify_data.get('title', 'instagram_media')
            ext = 'mp4' if 'videoUrl' in apify_data else 'jpg'
            media_type = 'video/mp4' if ext == 'mp4' else 'image/jpeg'
            
            return StreamingResponse(
                stream_from_url(direct_url, chunk_size=2097152),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{title}.{ext}"',
                    "Cache-Control": "no-cache",
                    "Accept-Ranges": "bytes"
                }
            )
        except Exception as apify_err:
            logger.warning(f"Apify failed: {apify_err}. Falling back to yt-dlp.")
        
        # Fallback: Original yt-dlp streaming
        direct_url, title, ext = await get_instagram_info_and_url(url)
        media_type = 'video/mp4' if ext in ['mp4', 'mov'] else 'image/jpeg'
        
        return StreamingResponse(
            stream_from_url(direct_url, chunk_size=2097152),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{title}.{ext}"',
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes"
            }
        )
        
    except Exception as e:
        logger.error(f"Instagram stream error: {e}")
        raise HTTPException(status_code=500, detail=f"Stream failed: {str(e)}")
