FROM python:3.11-slim

# Prevent writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (needed for general scientific compiling if any, and postgres connectivity)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . /app/

EXPOSE 8000

# We will run migrations and start the server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
