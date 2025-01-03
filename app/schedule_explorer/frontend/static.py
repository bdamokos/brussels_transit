from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI()

# Get the directory containing this file
current_dir = Path(__file__).parent

# Mount the static files
app.mount("/", StaticFiles(directory=current_dir, html=True), name="static") 