
To run backend:
cd app/schedule_explorer && uvicorn backend.main:app --reload

To run frontend:
python3 -m http.server 8080 --directory frontend/