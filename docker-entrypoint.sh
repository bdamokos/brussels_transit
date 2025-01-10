#!/bin/sh

# Ensure directories exist with correct permissions
mkdir -p \
    "$CACHE_DIR/stib" \
    "$CACHE_DIR/delijn" \
    "$DOWNLOADS_DIR" \
    "$LOGS_DIR"

# Set permissions
chmod -R 777 \
    "$CACHE_DIR" \
    "$DOWNLOADS_DIR" \
    "$LOGS_DIR"

# Start the application
exec python start.py 