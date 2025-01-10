FROM python:3.12-slim

WORKDIR /app

ENV PROJECT_ROOT=/app
ENV CACHE_DIR=/app/cache
ENV DOWNLOADS_DIR=/app/downloads
ENV LOGS_DIR=/app/logs
ENV GTFS_PRECACHE_DIR=/app/app/schedule_explorer/backend

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN apt-get update && apt-get install -y \
    curl \
    nano \
    libmsgpack-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create necessary directories and set permissions
RUN mkdir -p \
    ${CACHE_DIR} \
    ${DOWNLOADS_DIR} \
    ${LOGS_DIR} \
    ${CACHE_DIR}/stib \
    ${CACHE_DIR}/delijn \
    && chmod -R 777 \
    ${CACHE_DIR} \
    ${DOWNLOADS_DIR} \
    ${LOGS_DIR}

COPY . .

# Compile GTFS precache tool
WORKDIR /app/app/schedule_explorer/backend
RUN make

# Return to app directory
WORKDIR /app

# Make entrypoint executable
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]

