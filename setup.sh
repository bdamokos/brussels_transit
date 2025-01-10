#!/bin/bash

# Create required directories
mkdir -p downloads cache logs
mkdir -p cache/stib cache/delijn

# Create log files if they don't exist
touch logs/legacy_app.log
touch logs/schedule_explorer.log

# Set permissions (readable/writable by all)
chmod -R 777 downloads cache
chmod 666 logs/*.log

echo "Created required directories and files with correct permissions" 