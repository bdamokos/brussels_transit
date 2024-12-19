
To run backend:
uvicorn app.schedule_explorer.backend.main:app --reload

To run frontend:
python3 -m http.server 8080 --directory frontend/