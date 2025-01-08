FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN apt-get update && apt-get install -y \
    curl \
    nano \
    libmsgpack-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && chmod -R 777 /app \
    && chown -R nobody:nogroup /app

USER nobody

# Compile GTFS precache tool
RUN cd app/schedule_explorer/backend && make

# Declare volumes for persistent storage
VOLUME ["downloads", "cache"]

CMD ["python", "start.py"]

