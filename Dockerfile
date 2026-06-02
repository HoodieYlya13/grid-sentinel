FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY django_control_plane/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
