# -------------------------------------------------------
# Stage 1: Build & Dependencies
# -------------------------------------------------------
FROM python:3.14-slim AS build

WORKDIR /app

# Install uv (pinned to match the version used locally)
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /uvx /usr/local/bin/

# Compile bytecode for faster startup; copy mode avoids hard-link issues
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install system build deps (ffmpeg + libpq needed at build time)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ffmpeg \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source (better layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY . .
RUN uv sync --frozen --no-dev

# Collect static files
RUN uv run python manage.py collectstatic --noinput


# -------------------------------------------------------
# Stage 2: Runtime Image (smaller)
# -------------------------------------------------------
FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Use the venv created by uv
ENV PATH="/app/.venv/bin:$PATH"

# Runtime-only system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    ffmpeg \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire built app (venv + source + staticfiles) from the build stage
COPY --from=build /app /app

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

# entrypoint.sh applies migrations then starts Gunicorn.
ENTRYPOINT ["/app/entrypoint.sh"]
