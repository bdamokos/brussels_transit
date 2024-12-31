FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN apt-get update && apt-get install -y \
    curl \
    nano \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && chown -R nobody:nogroup /app \
    && chmod -R 777 /app

USER nobody

CMD ["python", "start.py"]