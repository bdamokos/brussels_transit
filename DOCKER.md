<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Docker Support](#docker-support)
  - [Image Versioning](#image-versioning)
    - [Tag Usage Guidelines](#tag-usage-guidelines)
  - [Configuration (Alpha Stage)](#configuration-alpha-stage)
    - [If building locally:](#if-building-locally)
    - [If using the container registry:](#if-using-the-container-registry)
    - [Then for both methods:](#then-for-both-methods)
  - [Available Configurations](#available-configurations)
    - [1. Backend Only](#1-backend-only)
    - [2. Backend with Temporary ngrok Tunnel](#2-backend-with-temporary-ngrok-tunnel)
    - [3. Backend with Static ngrok Domain](#3-backend-with-static-ngrok-domain)
  - [Environment Variables](#environment-variables)
    - [Required for All Configurations](#required-for-all-configurations)
    - [Additional Variables for ngrok Configurations](#additional-variables-for-ngrok-configurations)
  - [Configuration Files](#configuration-files)
  - [Health Checks](#health-checks)
  - [Security](#security)
  - [Troubleshooting](#troubleshooting)
  - [Development](#development)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Docker Support

This repository provides Docker support for running the Public Transit application in different configurations. The repository contains two main applications:

1. Real-time Transit Display (port 5001)
2. Schedule Explorer (ports 8000, 8080)

## Image Versioning

Images are published to GitHub Container Registry (ghcr.io) under these scenarios:

1. **Stable Releases**: When a new release is published (non-pre-release)
   - Creates versioned tags (e.g., `v1.2.3`, `v1.2`)
   - Updates the `stable` and `latest` tags
   - Example: `ghcr.io/bdamokos/brussels-transit:stable`

2. **Development Builds**: On every push to main branch or manual trigger
   - Updates the `edge` tag
   - Example: `ghcr.io/bdamokos/brussels-transit:edge`

### Tag Usage Guidelines

- Use `:stable` or `:latest` for production environments (they are identical)
- Use `:edge` for testing new features and development
- Use version tags (e.g., `v1.2.3`) for reproducible deployments

Note: Old versions and untagged images are automatically cleaned up by GitHub Container Registry's retention policy.

## Configuration (Alpha Stage)

During this alpha stage, configuration is done by editing two files directly in the container.

### If building locally:
1. Start the container:
   ```bash
   docker compose -f docker-compose.backend.yaml up -d
   ```

### If using the container registry:
1. Pull and start the container:
   ```bash
   docker pull ghcr.io/bdamokos/brussels-transit:stable
   docker run -d -p 5001:5001 -p 8000:8000 -p 8080:8080 ghcr.io/bdamokos/brussels-transit:stable
   ```

Replace `stable` with the tag you want to use (e.g., `v1.2.3`, `edge`, `latest`).

### Then for both methods:
2. Get the container ID:
   ```bash
   docker ps
   ```

3. Enter the container:
   ```bash
   docker exec -it <container_id> bash
   ```

4. Edit the configuration files with nano:
   ```bash
   # Edit environment variables (API keys, etc.)
   nano .env

   # Edit application settings (stops, map config)
   nano app/config/local.py
   ```

5. Restart the container:
   ```bash
   # If using docker compose:
   docker compose -f docker-compose.backend.yaml restart

   # If using docker run:
   docker restart <container_id>
   ```

Note: This manual configuration process will be streamlined in future releases.

## Available Configurations

### 1. Backend Only
This is the basic configuration that runs both backend servers.

```bash
docker compose -f docker-compose.backend.yaml up
```

The servers will be available at:
- Real-time Transit Display: `http://localhost:5001`
- Schedule Explorer: `http://localhost:8000` (backend) and `http://localhost:8080` (web)

### 2. Backend with Temporary ngrok Tunnel
This configuration runs the backend servers and creates a temporary ngrok tunnel for external access.

```bash
docker compose -f docker-compose.ngrok-temp.yaml up
```

The servers will be available at:
- Locally:
  - Real-time Transit Display: `http://localhost:5001`
  - Schedule Explorer: `http://localhost:8000` and `http://localhost:8080`
- ngrok tunnel: Check the ngrok dashboard at `http://localhost:4040` for the public URL

### 3. Backend with Static ngrok Domain
This configuration runs the backend servers and creates an ngrok tunnel with a static domain.

```bash
docker compose -f docker-compose.ngrok-static.yaml up
```

The servers will be available at:
- Locally:
  - Real-time Transit Display: `http://localhost:5001`
  - Schedule Explorer: `http://localhost:8000` and `http://localhost:8080`
- Static domain: The domain specified in your `.env` file

## Environment Variables

### Required for All Configurations
Create a `.env` file with the following variables (depending on your API choice):
```env
# Real-time Transit Display APIs
STIB_API_KEY=your_stib_api_key
DELIJN_API_KEY=your_delijn_api_key
DELIJN_GTFS_STATIC_API_KEY=your_delijn_gtfs_static_key
DELIJN_GTFS_REALTIME_API_KEY=your_delijn_gtfs_realtime_key
BKK_API_KEY=your_bkk_api_key
MOBILITY_API_REFRESH_TOKEN=your_mobility_api_refresh_token # optional

# Port Configuration
PORT=5001  # For Real-time Transit Display
SCHEDULE_EXPLORER_PORT=8000  # For Schedule Explorer API
SCHEDULE_EXPLORER_WEB_PORT=8080  # For Schedule Explorer Web Interface
```

### Additional Variables for ngrok Configurations
For ngrok configurations, add these to your `.env` file:
```env
NGROK_AUTHTOKEN=your_ngrok_auth_token  # Required for both ngrok configurations
NGROK_DOMAIN=your-domain.ngrok-free.app  # Required only for static domain configuration
```

## Configuration Files

The application requires certain configuration files to run:

1. Real-time Transit Display:
   - A `local.py` configuration file will be automatically created from `local.py.example` if not present
   - You can customize it by mounting your own `local.py` file

2. Schedule Explorer:
   - Requires a `gtfs_config.json` file for GTFS data configuration
   - Example configuration is provided in `gtfs_config.json.example`


## Health Checks

All configurations include health checks to ensure service reliability:

- Backend services are checked every 10 seconds
- 5 retries are allowed
- 30-second startup grace period
- 5-second timeout for each health check

The health endpoints return a JSON response:
```json
{
  "status": "healthy"
}
```

## Security

- Images are regularly scanned for vulnerabilities using Trivy
- Critical and high severity vulnerabilities are blocked in CI/CD
- Non-root user is used in the container
- Minimal base image (python:3.13-slim) is used

## Troubleshooting

1. **Container fails to start**
   - Check if all required environment variables are set
   - Verify ports (5001, 8000, 8080) are not in use
   - Check logs: `docker compose -f <config-file> logs`

2. **ngrok tunnel not working**
   - Verify your ngrok authentication token
   - Check ngrok logs: `docker compose -f <config-file> logs ngrok`
   - Visit the ngrok dashboard at `http://localhost:4040`

3. **Health check failing**
   - Check if the applications are running:
     ```bash
     curl http://localhost:5001/health  # Real-time Transit Display
     curl http://localhost:8000/health  # Schedule Explorer API
     ```
   - Inspect logs for application errors
   - Verify network connectivity between containers

4. **Configuration issues**
   - Verify `local.py` is properly configured
   - Check `gtfs_config.json` exists and is valid
   - Ensure all required API keys are set in `.env`

## Development

When developing locally, you can use the following commands:

```bash
# Build and run with changes
docker compose -f <config-file> up --build

# View logs
docker compose -f <config-file> logs -f

# Stop services
docker compose -f <config-file> down
``` 