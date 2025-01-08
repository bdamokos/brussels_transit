FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN apt-get update && apt-get install -y \
    curl \
    nano \
    libmsgpack-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && mkdir -p downloads cache logs \
    && chmod -R 777 /app \
    && chown -R nobody:nogroup /app \
    && mkdir -p /app/cache/stib /app/cache/delijn /app/logs \
    && chmod -R 777 /app/cache /app/logs \
    && touch /app/logs/legacy_app.log /app/logs/schedule_explorer.log \
    && chmod 666 /app/logs/legacy_app.log /app/logs/schedule_explorer.log

COPY . .

# Compile GTFS precache tool with debug symbols and memory alignment
RUN cd app/schedule_explorer/backend && \
    CFLAGS="-Wall -O2 -g -fno-strict-aliasing" make clean && \
    CFLAGS="-Wall -O2 -g -fno-strict-aliasing" make

USER nobody

CMD ["python", "start.py"]

