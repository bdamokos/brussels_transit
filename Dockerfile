FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip/*

# Copy the application files
COPY app/ .
COPY app/schedule_explorer/ schedule_explorer/

# Create default configs if not exists
COPY app/config/local.py.example app/config/local.py

# Create logs directory and set permissions
RUN mkdir -p /app/logs && \
    mkdir -p /app/schedule_explorer/logs && \
    chown -R nobody:nogroup /app && \
    chmod -R 755 /app && \
    chmod 777 /app/logs && \
    chmod 777 /app/schedule_explorer/logs && \
    touch /app/logs/app.log && \
    touch /app/schedule_explorer/logs/app.log && \
    chmod 666 /app/logs/app.log && \
    chmod 666 /app/schedule_explorer/logs/app.log

# Switch to non-root user
USER nobody

# Expose the ports
EXPOSE 5001 8080 8000

# Command to run the application
CMD ["python", "main.py"]