# Build stage
FROM python:3.13-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip/*

# Final stage
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    nano \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && mkdir -p /app/logs /app/schedule_explorer/logs /app/cache /app/schedule_explorer/cache \
    && chown -R nobody:nogroup /app \
    && chmod -R 755 /app \
    && chmod 775 /app/logs /app/schedule_explorer/logs /app/cache /app/schedule_explorer/cache

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/

# Copy application files
COPY app/ .
COPY app/schedule_explorer/ schedule_explorer/

# Switch to non-root user
USER nobody

# Expose the ports
EXPOSE 5001 8080 8000

# Command to run the application
CMD ["python", "main.py"]