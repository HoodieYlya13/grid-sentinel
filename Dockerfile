FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces run the container as UID 1000
RUN useradd --create-home --uid 1000 user \
    && mkdir /app \
    && chown user:user /app

WORKDIR /app

COPY django_control_plane/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . /app/

RUN chmod +x /app/start.sh

USER user

EXPOSE 7860

CMD ["/app/start.sh"]
