






# FROM python:3.11-slim

# WORKDIR /app

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     gcc \
#     curl \
#     && rm -rf /var/lib/apt/lists/*

# # Copy requirements and install Python dependencies
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy application code
# COPY . .

# # Create non-root user for security
# RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
# USER app

# # Expose port
# EXPOSE 8000

# # Health check for Fly.io
# HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
#   CMD curl -f http://localhost:8000/health || exit 1

# # Production command (no --reload for production)
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]





FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies - enhanced for bulk operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    build-essential \
    libgomp1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for better performance
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security - fixed permissions
RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/uploads /app/exports /app/logs && \
    chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

# Health check - honours $PORT (Railway/most PaaS inject it)
HEALTHCHECK --interval=30s --timeout=30s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Production command. SHELL form (not exec/JSON) so $PORT expands. On Railway the
# railway.json startCommand (railway-start.sh) overrides this and ALSO runs the
# migration first; this CMD is the fallback for a plain `docker run`.
CMD gunicorn app.main:app -w ${WEB_CONCURRENCY:-4} -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} --max-requests 1000 --max-requests-jitter 100 \
    --preload --timeout 120
