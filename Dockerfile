# -------------------------------------------------------
# Stage 1: Build & Dependencies
# -------------------------------------------------------
FROM python:3.10-slim AS build

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (includes ffmpeg + postgres libs)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput


# -------------------------------------------------------
# Stage 2: Runtime Image (smaller)
# -------------------------------------------------------
FROM python:3.10-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies (ffmpeg + PostgreSQL client)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies from build image
COPY --from=build /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=build /usr/local/bin /usr/local/bin

# Copy project code & static files
COPY --from=build /app /app

# Expose Django port
EXPOSE 8000

# Run Gunicorn (recommended for production)
CMD ["gunicorn", "withthanks.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
