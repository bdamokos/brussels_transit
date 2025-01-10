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

# Create necessary directories and files with correct permissions
RUN mkdir -p \
    "$CACHE_DIR/stib" \
    "$CACHE_DIR/delijn" \
    "$DOWNLOADS_DIR" \
    "$LOGS_DIR" \
    && touch "$LOGS_DIR/legacy_app.log" \
    && touch "$LOGS_DIR/schedule_explorer.log" \
    && chown -R nobody:nogroup /app \
    && chmod -R 777 "$CACHE_DIR" "$DOWNLOADS_DIR" \
    && chmod 666 "$LOGS_DIR"/*.log

COPY . .

# Compile GTFS precache tool
RUN cd app/schedule_explorer/backend && make

USER nobody

CMD ["python", "start.py"]

