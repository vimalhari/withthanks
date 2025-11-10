# # Use official Python image
# FROM python:3.10

# # Set working directory inside the container
# WORKDIR /app

# # Prevent Python from writing .pyc files and using stdout buffering
# ENV PYTHONDONTWRITEBYTECODE=1
# ENV PYTHONUNBUFFERED=1

# # Copy dependency file
# COPY requirements.txt /app/

# # Install dependencies
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy your entire Django project
# COPY . /app/

# RUN python manage.py collectstatic --noinput

# # Expose Django default port
# EXPOSE 8000

# # Run migrations and start Django server
# CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]



# Use official Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Environment setup
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Start Gunicorn server
CMD ["gunicorn", "withthanks.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
