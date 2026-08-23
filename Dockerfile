# ResearchMind - Production Containerfile
# Base: Python 3.12 slim for minimal footprint and security
FROM python:3.12-slim AS base

# System configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    PORT=8080 \
    HOST=0.0.0.0 \
    APP_ENV=production

# Install minimal OS dependencies if needed and create non-root user
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash --uid 10001 appuser

WORKDIR /app

# Install dependencies in a separate layer for build cache optimization
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copy application source
COPY backend/ /app/backend/

# Set file ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to unprivileged user
USER appuser

# Expose target HTTP service port
EXPOSE 8080

# Health check using standard Python urllib
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 8080)}/healthz')" || exit 1

# Default runtime entrypoint: FastAPI production application via uvicorn factory
CMD ["python", "-m", "uvicorn", "app.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
