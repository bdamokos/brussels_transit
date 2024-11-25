# Brussels Public Transport Display System

A real-time display system showing waiting times for STIB/MIVB and De Lijn public transport in Brussels.

## Features

- Real-time waiting times for STIB/MIVB buses, trams and metros
- Real-time waiting times for De Lijn buses
- Configurable display of multiple stops
- Auto-refresh of waiting times

## Getting Started

### Prerequisites

- API keys for STIB and De Lijn (see below)

### Installation

1. Clone this repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment:
   - Windows: `.venv\Scripts\activate`
   - Linux/Mac: `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `local.py.example` to `local.py` and add your API keys to the `.env` file
6. Run the application: `python app/main.py`
7. Access the application at `http://localhost:5001`

### Running with Docker

1. Copy `docker-compose.yaml.example` to `docker-compose.yaml` and add your API keys to the `.env` file
2. Copy `local.py.example` to `local.py` and add your API keys to the `.env` file - change the variables as needed
3. For outside access, an example is provided using ngrok. See `docker-compose.yaml.example` for details. Otherwise, remove the `ngrok-static` service.
4. Run the application: `docker compose up`
5. Access the application at `http://localhost:5001` or the ngrok URL

## Getting API Access

### STIB/MIVB API

1. Go to the [STIB Open Data Portal](https://opendata.stib-mivb.be/)
2. Create an account and log in
3. Generate your API key in your account settings
4. Add the key to your `.env` file

### De Lijn API

1. Visit the [De Lijn Developer Portal](https://data.delijn.be/)
2. Create an account
3. Subscribe to both:
   - "Open Data Free Subscribe Here" 
   - "De Lijn GTFS Realtime"
   - "De Lijn GTFS Static"
4. Add the keys to your `.env` file

## Figuring out stop IDs

### Stib
Either:
- Explore the open data portal and find the stop ID (https://opendata.stib-mivb.be/) (You can filter by the 'where' field to narrow down the search. E.g. where: pointid="1234" to get information about a specific stop.)
- Use the [STIB stop finder](https://www.stib-mivb.be/index.htm?l=fr) and look for `stop=` in the URL
- For each line, one direction is designated as "City" and the other as "Suburb" - it is not always the same direction as you might expect.

### De Lijn
Either:
- Use the [De Lijn stop finder](https://www.delijn.be/nl/haltes/) and look for the stop ID in the URL
- Explore the open data portal and find the stop ID (https://data.delijn.be/) (Sometimes it is useful to know that Brussels is under gemeenteeNummer=3)

## Configuration

## Initial Setup

1. Copy the example configuration files:   ```bash
   cp config/local.py.example config/local.py
   cp .env.example .env   ```

2. Edit `config/local.py` to set your:
   - Monitored stops and lines
   - Map center coordinates and zoom level
   - Other custom settings

3. Edit `.env` to add your API keys:
   - STIB/MIVB API key
   - De Lijn API keys (regular, GTFS static, and GTFS realtime)
   - NGROK_AUTHTOKEN (if using ngrok)
   - NGROK_DOMAIN (if using ngrok)

## Configuration Files

- `config/default.py`: Default settings (do not edit)
- `config/local.py`: Your local settings (edit this)
- `.env`: Environment variables and API keys

## Known Issues and Limitations

- The De Lijn setup is not yet fully set up for multiple monitored lines.
- SNCB and TEC are not yet supported.
- Where the API provides multiple languages, English and French are taken as the default, depending on the API. (E.g. Station names for STIB in French, service messages for STIB in English)
- Timetables are not yet supported. (This information is available in the GTFS data of both STIB and De Lijn)


