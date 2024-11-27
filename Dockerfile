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

# Create cache directory
RUN mkdir -p cache

# Copy the application files
COPY app/ .
COPY cache/ /app/cache/

# Create logs directory and set permissions
RUN mkdir -p /app/logs && \
    chown -R nobody:nogroup /app && \
    chmod -R 755 /app && \
    chmod 777 /app/logs && \
    touch /app/logs/app.log && \
    chmod 666 /app/logs/app.log

# Switch to non-root user
USER nobody

# Expose the port the app runs on
EXPOSE 5001

# Command to run the application
CMD ["python", "main.py"]