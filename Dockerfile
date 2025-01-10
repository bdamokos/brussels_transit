FROM python:3.12-slim

WORKDIR /app

ENV PROJECT_ROOT=/app
ENV CACHE_DIR=/app/cache
ENV DOWNLOADS_DIR=/app/downloads
ENV LOGS_DIR=/app/logs

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN apt-get update && apt-get install -y \
    curl \
    nano \
    libmsgpack-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

COPY . .

# Compile GTFS precache tool
RUN cd app/schedule_explorer/backend && make

# Make entrypoint executable
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER nobody

ENTRYPOINT ["docker-entrypoint.sh"]

