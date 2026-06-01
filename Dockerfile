# ----------------------------------------------------------------------------
# Stage 1: Builder – install dependencies and prepare the environment
# ----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Install system dependencies required for building some Python packages (e.g., psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Upgrade pip and install dependencies (including build dependencies)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------------------------
# Stage 2: Runtime – create a minimal image
# ----------------------------------------------------------------------------
FROM python:3.11-slim

# Install runtime system dependencies (only libpq for psycopg2, no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a non‑root user to run the application
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 appuser

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:$PATH"

WORKDIR /app

# Copy installed Python packages from the builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the application code
COPY . .

# Create directories for uploads and logs and set ownership
RUN mkdir -p /app/uploads /app/logs && \
    chown -R appuser:appgroup /app && \
    chmod -R 755 /app/uploads /app/logs

# Switch to non‑root user
USER appuser

# Expose the port Gunicorn will listen on
EXPOSE 8000

# Health check (matches docker-compose.yml)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run Gunicorn with optimized settings
# Adjust workers based on CPU cores, threads for async I/O
# Using gthread worker class for better concurrency
CMD ["gunicorn", "--workers", "2", "--threads", "4", "--worker-class", "gthread", 
     "--max-requests", "1000", "--max-requests-jitter", "100", 
     "--bind", "0.0.0.0:8000", "--factory", "app:create_app"]