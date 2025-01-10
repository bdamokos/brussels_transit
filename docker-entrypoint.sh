#!/bin/sh
set -e

# Function to ensure directory exists and has correct permissions
ensure_dir() {
    dir="$1"
    if [ ! -d "$dir" ]; then
        echo "Creating directory: $dir"
        mkdir -p "$dir"
    fi
    chmod 777 "$dir"
}

# Function to ensure log file exists and has correct permissions
ensure_log() {
    log="$1"
    if [ ! -f "$log" ]; then
        echo "Creating log file: $log"
        touch "$log"
    fi
    chmod 666 "$log"
}

# Ensure all required directories exist with correct permissions
ensure_dir "$CACHE_DIR"
ensure_dir "$CACHE_DIR/stib"
ensure_dir "$CACHE_DIR/delijn"
ensure_dir "$DOWNLOADS_DIR"
ensure_dir "$LOGS_DIR"

# Ensure log files exist with correct permissions
ensure_log "$LOGS_DIR/legacy_app.log"
ensure_log "$LOGS_DIR/schedule_explorer.log"

# Start the application
exec python start.py 