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
    && mkdir -p /app/cache/stib /app/cache/delijn \
    && chmod -R 777 /app/cache \
    && chmod -R 777 /app/logs

COPY . .

# Compile GTFS precache tool
RUN cd app/schedule_explorer/backend && make

USER nobody

CMD ["python", "start.py"]

