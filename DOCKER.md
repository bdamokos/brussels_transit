# Docker Support

This repository provides Docker support for running the Public Transit application in different configurations. You can choose between three different setups depending on your needs.

## Available Configurations

### 1. Backend Only
This is the basic configuration that runs only the backend server.

```bash
docker compose -f docker-compose.backend.yaml up
```

The server will be available at `http://localhost:5001`.

### 2. Backend with Temporary ngrok Tunnel
This configuration runs the backend server and creates a temporary ngrok tunnel for external access.

```bash
docker compose -f docker-compose.ngrok-temp.yaml up
```

The server will be available at:
- Locally: `http://localhost:5001`
- ngrok tunnel: Check the ngrok dashboard at `http://localhost:4040` for the public URL

### 3. Backend with Static ngrok Domain
This configuration runs the backend server and creates an ngrok tunnel with a static domain.

```bash
docker compose -f docker-compose.ngrok-static.yaml up
```

The server will be available at:
- Locally: `http://localhost:5001`
- Static domain: The domain specified in your `.env` file

## Environment Variables

### Required for All Configurations
Create a `.env` file with the following variables (depending on your API choice):
```env
STIB_API_KEY=your_stib_api_key
DELIJN_API_KEY=your_delijn_api_key
DELIJN_GTFS_STATIC_API_KEY=your_delijn_gtfs_static_key
DELIJN_GTFS_REALTIME_API_KEY=your_delijn_gtfs_realtime_key
BKK_API_KEY=your_bkk_api_key
MOBILITY_API_REFRESH_TOKEN=your_mobility_api_refresh_token # optional
PORT=5001  # Optional, defaults to 5001
```

### Additional Variables for ngrok Configurations
For ngrok configurations, add these to your `.env` file:
```env
NGROK_AUTHTOKEN=your_ngrok_auth_token  # Required for both ngrok configurations
NGROK_DOMAIN=your-domain.ngrok-free.app  # Required only for static domain configuration
```

## Resource Limits

Each configuration comes with predefined resource limits:

### Backend Service
- CPU: 0.5 cores
- Memory: 512MB

### ngrok Service (when applicable)
- CPU: 0.25 cores
- Memory: 256MB

You can adjust these limits in the respective docker-compose files.

## Health Checks

All configurations include health checks to ensure service reliability:

- Backend service is checked every 10 seconds
- 5 retries are allowed
- 30-second startup grace period
- 5-second timeout for each health check

The health endpoint (`/health`) returns a JSON response:
```json
{
  "status": "healthy"
}
```

## Using Pre-built Images

Pre-built images are available from GitHub Container Registry:

```bash
# Pull backend-only image
docker pull ghcr.io/bdamokos/brussels-transit:latest

# Pull backend with temporary ngrok support
docker pull ghcr.io/bdamokos/brussels-transit:latest-ngrok-temp

# Pull backend with static ngrok support
docker pull ghcr.io/bdamokos/brussels-transit:latest-ngrok-static
```

## Security

- Images are regularly scanned for vulnerabilities using Trivy
- Critical and high severity vulnerabilities are blocked in CI/CD
- Non-root user is used in the container
- Minimal base image (python:3.13-slim) is used

## Troubleshooting

1. **Container fails to start**
   - Check if all required environment variables are set
   - Verify port 5001 is not in use
   - Check logs: `docker compose -f <config-file> logs`

2. **ngrok tunnel not working**
   - Verify your ngrok authentication token
   - Check ngrok logs: `docker compose -f <config-file> logs ngrok`
   - Visit the ngrok dashboard at `http://localhost:4040`

3. **Health check failing**
   - Check if the application is running: `curl http://localhost:5001/health`
   - Inspect logs for application errors
   - Verify network connectivity between containers

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