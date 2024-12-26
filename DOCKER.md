# Docker Support

This repository provides Docker support for running the Public Transit application in different configurations. The repository contains two main applications:

1. Real-time Transit Display (port 5001)
2. Schedule Explorer (ports 8000, 8080)

## Image Versioning

Images are published to GitHub Container Registry (ghcr.io) under three different scenarios:

1. **Stable Releases**: When a new release is published (non-pre-release)
   - Creates versioned tags (e.g., `v1.2.3`, `v1.2`)
   - Updates the `stable` tag
   - Available in three variants:
     - Default: `ghcr.io/bdamokos/brussels-transit:v1.2.3` or `:stable`
     - Temporary ngrok: `ghcr.io/bdamokos/brussels-transit:v1.2.3-ngrok-temp` or `:stable-ngrok-temp`
     - Static ngrok: `ghcr.io/bdamokos/brussels-transit:v1.2.3-ngrok-static` or `:stable-ngrok-static`

2. **Pre-releases**: When an alpha/beta/rc release is published
   - Creates versioned tags (e.g., `v1.2.3-rc.1`)
   - Updates the `edge` tag
   - Available in three variants:
     - Default: `ghcr.io/bdamokos/brussels-transit:v1.2.3-rc.1` or `:edge`
     - Temporary ngrok: `ghcr.io/bdamokos/brussels-transit:v1.2.3-rc.1-ngrok-temp` or `:edge-ngrok-temp`
     - Static ngrok: `ghcr.io/bdamokos/brussels-transit:v1.2.3-rc.1-ngrok-static` or `:edge-ngrok-static`

3. **Weekly Updates**: Every Sunday at midnight UTC (only if there were changes in the last week)
   - Updates the `latest` tags
   - Available in three variants:
     - Default: `ghcr.io/bdamokos/brussels-transit:latest`
     - Temporary ngrok: `ghcr.io/bdamokos/brussels-transit:latest-ngrok-temp`
     - Static ngrok: `ghcr.io/bdamokos/brussels-transit:latest-ngrok-static`

### Tag Usage Guidelines

- Use `:stable` for production environments
- Use `:edge` for testing new features
- Use `:latest` for development environments
- Use version tags (e.g., `v1.2.3`) for reproducible deployments

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

## Resource Limits

Each configuration comes with predefined resource limits:

### Backend Services
- CPU: 0.5 cores
- Memory: 512MB

### ngrok Service (when applicable)
- CPU: 0.25 cores
- Memory: 256MB

You can adjust these limits in the respective docker-compose files.

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