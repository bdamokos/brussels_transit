<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Public Transport Waiting Times](#public-transport-waiting-times)
  - [Features](#features)
  - [Use-case](#use-case)
  - [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
    - [Installation](#installation)
    - [Running the Application](#running-the-application)
    - [Running with Docker](#running-with-docker)
  - [Getting API Access](#getting-api-access)
    - [STIB/MIVB API (Belgium)](#stibmivb-api-belgium)
    - [De Lijn API (Belgium)](#de-lijn-api-belgium)
    - [SNCB (Belgium)](#sncb-belgium)
    - [BKK (Budapest)](#bkk-budapest)
    - [Mobility Database](#mobility-database)
  - [Figuring out stop IDs](#figuring-out-stop-ids)
    - [Stib](#stib)
    - [De Lijn](#de-lijn)
  - [Configuration](#configuration)
  - [Initial Setup](#initial-setup)
  - [Configuration Files](#configuration-files)
  - [Known Issues and Limitations](#known-issues-and-limitations)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Public Transport Waiting Times

Creates a dashboard showing waiting times for implemented public transport companies' stops, ordered by distance from a given point (map centre or user's current location).

The aim is for a modular design that allows for easy addition of new transit providers, including in other countries.

Currently supported real-time waiting times:
- Belgium: STIB, De Lijn, SNCB
- Hungary: BKK

Schedule based waiting times: supported in 70 countries covered by the Mobility Database.

Alongside realtime waiting times, it creates a dashboard to browse stops and routes from static GTFS data that it can dynamically download from the Mobility Database.

## Features
- Real-time waiting times for  buses, trams and metros
- Configurable display of multiple stops
- Auto-refresh of waiting times
- API that can be used by other applications (e.g. a Raspberry Pi display)
- Schedule Explorer: A web interface to explore GTFS schedules and plan routes (beta)

![Vehicle locations](docs/images/vehicle_tracking_on_the_frontend.png)

![Screenshot of the web portal the application creates](docs/images/webportal.png)

![All stops being loaded in the Stop Explorer view](docs/images/map_loading_stop_explorer.gif)

## Use-case
Mainly to power smart home displays that provide transit data (e.g. next train departures, waiting times at nearby bus stops).

Reference implementation: [Raspberry Pi Waiting Time Display (ridiculously sped up)](https://github.com/bdamokos/rpi_waiting_time_display)

## Getting Started

### Prerequisites

- API keys for STIB and De Lijn (see below) - requires free registration

### Installation
*Docker*

See [DOCKER.md](DOCKER.md) for how to install it directly with Docker.

*Traditional way*
1. Clone this repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate the virtual environment:
   - Windows: `.venv\Scripts\activate`
   - Linux/Mac: `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `local.py.example` to `local.py` and add your API keys to the `.env` file

### Running the Application

You can run all components (legacy app, Schedule Explorer frontend and backend) with a single command:

```bash
python start.py
```

This will start:
- Waiting time dashboard http://localhost:5001 (limited to hardcoded providers)
- Schedule Explorer frontend on http://localhost:8080 (GTFS schedule explorer - allows loading the GTFS data of all providers who are in the Mobility Database and do not require specific authentication)
- Schedule Explorer backend on http://localhost:8000 (GTFS schedule explorer API)

To stop all components, press Ctrl+C.

Alternatively, you can run individual components:
- Legacy app only: `python app/main.py`
- Schedule Explorer backend: `cd app/schedule_explorer && uvicorn backend.main:app --reload`
- Schedule Explorer frontend: `cd app/schedule_explorer/frontend && python -m http.server 8080`

### Running with Docker

1. Copy `docker-compose.yaml.example` to `docker-compose.yaml` and add your API keys to the `.env` file
2. Copy `local.py.example` to `local.py` and add your API keys to the `.env` file - change the variables as needed
3. For outside access, an example is provided using ngrok. See `docker-compose.yaml.example` for details. Otherwise, remove the `ngrok-static` service.
4. Run the application: `docker compose up`
5. Access the application at `http://localhost:5001` or the ngrok URL

## Getting API Access

### STIB/MIVB API (Belgium)

1. Go to the [STIB Open Data Portal](https://opendata.stib-mivb.be/)
2. Create an account and log in
3. Generate your API key in your account settings
4. Add the key to your `.env` file as "STIB_API_KEY"

### De Lijn API (Belgium)

1. Visit the [De Lijn Developer Portal](https://data.delijn.be/)
2. Create an account
3. Subscribe to both:
   - "Open Data Free Subscribe Here" 
   - "De Lijn GTFS Realtime"
   - "De Lijn GTFS Static"
4. Add the keys to your `.env` file (as DELIJN_API_KEY, DELIJN_GTFS_STATIC_API_KEY, and 
DELIJN_GTFS_REALTIME_API_KEY)

### SNCB (Belgium)

Note that the app works without signing an agreement with SNCB through the mirrored data provided by [GTFS.be](https://gtfs.be/).

1. Visit https://opendata.sncb.be/
2. Register and request an agreement
3. Once both parties have signed the agreement, you will receive a link to a page where the GTFS real time feed is linked
4. Add the url to your `.env` file as "SNCB_GTFS_REALTIME_API_URL"

### BKK (Budapest)

1. Visit https://opendata.bkk.hu/data-sources
2. Register and get a key under the key management option
3. Add the keys to your `.env` file

### Mobility Database

Without an API key, you are limited to a CSV mirror of the data, that is not fully up to date.

1. Go to https://mobilitydatabase.org
2. Create an account
3. Get your API refresh key
4. Add the keys to your `.env` file


## Figuring out stop IDs

General method:

- Go to the GTFS downloader interface of the Schedule Explorer, download the GTFS data for your provider
- Switch to the Stop explorer tab, type in your stop name
- Select the stops that appear, look for the route and direction you want to monitor
- Note down the stop_id for the relevant stop

Note that the Schedule Explorer works with a wide range of providers. There is a schedule based interface that displays the upcoming arrivals at a stop on port 8000. 
There is also a similar interface that displays realtime waiting times on port 5001 for the 4 providers that are currently implemented.
  
### Stib
Alternatively:
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
