# Mbuvi Tech — Social Media Downloader

> Download videos and audio from YouTube, X (Twitter), TikTok, Instagram, and Facebook.  
> Fast · Free · No sign-up · No watermarks.

---

## Features

| Feature | Detail |
|---|---|
| **YouTube** | Search by title or paste a URL. Download MP3 (with embedded cover art) or MP4 up to 1080p |
| **X (Twitter)** | Stream video directly from any public post |
| **TikTok** | No-watermark video or audio-only via tikwm API |
| **Instagram** | Reels and public videos via Apify + yt-dlp fallback |
| **Facebook** | Public video downloads |
| **Metadata** | YouTube audio includes title, artist, and album artwork embedded in the MP3 |
| **Mobile-first** | Fully responsive — works on any screen size |
| **No limits** | No accounts, no caps, no queues |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | **FastAPI** + **Uvicorn** |
| Media extraction | **yt-dlp** (with Node.js JS-challenge solver) |
| Audio processing | **ffmpeg** (merge, thumbnail embed) |
| TikTok | [tikwm.com](https://tikwm.com) API |
| Instagram | Apify actor + yt-dlp fallback |
| Frontend | Vanilla HTML / CSS / JS (zero frameworks) |
| Fonts | Syne · DM Mono (Google Fonts) |
| Deployment | **Koyeb** (Docker) |
| WhatsApp Bot | Separate service at [sessions.mbuvitech.site](https://sessions.mbuvitech.site) |

---

## Project Structure

```
fastapiopt/
├── main.py              # FastAPI app entry point — mounts all routers
├── modules/
│   ├── youtube.py       # YouTube download + stream endpoints
│   ├── tiktok.py        # TikTok video/audio via tikwm
│   ├── instagram.py     # Instagram via Apify + yt-dlp fallback
│   ├── facebook.py      # Facebook video download
│   └── x.py             # X (Twitter) video stream
├── static/
│   ├── index.html       # Frontend UI
│   ├── style.css        # Signal design system (dark, acid-yellow accent)
│   ├── script.js        # MediaDownloader class
│   └── icon99.png       # Favicon
├── temp/                # Temporary download files (auto-cleaned)
├── cookies.txt          # YouTube cookies (yt-dlp authentication)
├── Dockerfile           # Production image (Python + Node.js + ffmpeg)
├── requirements.txt     # Python dependencies
├── Procfile             # Process definition
└── fly.toml             # Fly.io config (legacy — now on Koyeb)
```

---

## API Endpoints

### YouTube

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/download/audio/stream` | Download audio as MP3 with embedded thumbnail |
| `GET` | `/download/video/stream` | Download video as MP4 (with ffmpeg merge) |
| `GET` | `/download/audio` | Proxy audio via direct URL |
| `GET` | `/download/video` | Proxy video via direct URL |
| `GET` | `/download/audio/redirect` | Redirect to raw audio URL |
| `GET` | `/download/video/redirect` | Redirect to raw video URL |

**Query params:** `song` (YouTube URL, required) · `quality` (128K / 192K / 320K for audio; 144p–1080p for video)

### TikTok

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/tiktokurl` | Download TikTok video (no watermark) |
| `GET` | `/api/tiktoaudio` | Download TikTok audio only |

**Query param:** `url`

### Instagram

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/download/iglink` | Download Instagram reel or video |

**Query param:** `url`

### Facebook

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/fburl` | Download Facebook video |

**Query param:** `url`

### X (Twitter)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/stream/xurl` | Stream X video to browser |

**Query param:** `url`

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 22+
- ffmpeg
- yt-dlp

```bash
# Clone
git clone https://github.com/cheekydavy/fastapiopt
cd fastapiopt

# Install Python deps
pip install -r requirements.txt

# Create temp directory
mkdir -p temp

# Add your cookies.txt (YouTube authentication)
# Export from browser using yt-dlp's cookie guide:
# https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp

# Run
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000`

---

## Docker

```bash
# Build
docker build -t mbuvi-downloader .

# Run
docker run -p 8000:8000 mbuvi-downloader
```

The Dockerfile installs Python 3.11, Node.js 22, and ffmpeg in one image.

---

## Environment / Secrets

| Variable / File | Purpose |
|---|---|
| `cookies.txt` | YouTube cookies for yt-dlp authentication. Place in project root. |

The app searches for `cookies.txt` in several locations (`/app/cookies.txt`, `./cookies.txt`, etc.) at runtime.

---

## YouTube Format Strategy

YouTube now requires JavaScript challenge solving (`--js-runtimes node --remote-components ejs:github`) to decrypt video format URLs. Without Node.js, yt-dlp falls back to image-only streams.

**Audio:** `bestaudio` → converted to MP3 via ffmpeg with embedded thumbnail  
**Video:** itag-based format codes (`22` for 720p, `137+140` for 1080p, etc.) with `best[height<=N]` fallbacks — same strategy as the companion ytdownloader service.

---

## WhatsApp Bot

Download directly inside WhatsApp without opening a browser.  
👉 [sessions.mbuvitech.site](https://sessions.mbuvitech.site)

---

## Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — media extraction engine
- [tikwm](https://tikwm.com) — TikTok no-watermark API
- [Apify](https://apify.com) — Instagram scraping
- [FastAPI](https://fastapi.tiangolo.com) — backend framework
- [Syne](https://fonts.google.com/specimen/Syne) + [DM Mono](https://fonts.google.com/specimen/DM+Mono) — typography

---

## Legal

Only download content you have rights to use or content in the public domain.  
This tool is intended for personal use. Always respect copyright law and each platform's terms of service.

---

*Built by [Davy Mbuvi](https://github.com/cheekydavy)*
