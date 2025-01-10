from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import os
from pathlib import Path

app = FastAPI()

# Get the directory containing this file
current_dir = Path(__file__).parent

# Mount static files (js, css, etc.)
app.mount("/js", StaticFiles(directory=current_dir / "js"), name="js")
app.mount("/css", StaticFiles(directory=current_dir / "css"), name="css")

# Set up templates
templates = Jinja2Templates(directory=str(current_dir))

# Get environment variables with defaults
SCHEDULE_EXPLORER_API_URL = os.getenv('SCHEDULE_EXPLORER_API_URL', 'http://localhost:8000')

@app.get("/")
async def read_root(request: Request):
    """Serve the index page with injected environment variables"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "api_url": SCHEDULE_EXPLORER_API_URL
    })

@app.get("/index.html")
async def read_index(request: Request):
    """Redirect /index.html to /"""
    return RedirectResponse(url="/")

@app.get("/stop_explorer.html")
async def read_stop_explorer(request: Request):
    """Serve the stop explorer page with injected environment variables"""
    return templates.TemplateResponse("stop_explorer.html", {
        "request": request,
        "api_url": SCHEDULE_EXPLORER_API_URL
    })

@app.get("/get_gtfs_data.html")
async def read_gtfs_data(request: Request):
    """Serve the GTFS data manager page with injected environment variables"""
    return templates.TemplateResponse("get_gtfs_data.html", {
        "request": request,
        "api_url": SCHEDULE_EXPLORER_API_URL
    }) 