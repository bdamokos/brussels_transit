from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime

app = FastAPI()

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# Get the directory containing this file
current_dir = Path(__file__).parent

# Mount the static files
app.mount("/", StaticFiles(directory=current_dir, html=True), name="static") 