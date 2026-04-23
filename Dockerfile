FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Node.js (required for yt-dlp JS challenge solving)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify installs
RUN node -v && npm -v && ffmpeg -version

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /app/static /app/modules /app/temp

# Copy application files
COPY main.py .
COPY cookies.txt .
COPY static/ /app/static/
COPY modules/ /app/modules/

# Create temp directory with proper permissions
RUN chmod -R 777 /app/temp

# Expose port
EXPOSE 8000

# Set environment variables
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop"]
